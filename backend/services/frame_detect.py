"""多图框图幅检测与切片 —— 矢量检测 × 文本/视觉两重判定（2026-09-23 v2）

一张 DWG/DXF 常含多个标准图框（每框 = 一张独立图纸）。检测出各框世界坐标后
切成多页 PNG（{fid}_p1..pN），直接复用既有 PDF 多页预览/问答机制，前端零改动。

实测教训（v1 推翻重建）：
- 图纸单位不一定是 mm（样图模型空间 1mm≈154 单位）→ 一切绝对 mm 阈值失效，
  只保留"长宽比"这条与单位无关的几何特征（ISO 图幅全系列 ≈ √2）
- 整图 extents 常被孤立脏几何撑爆（z 跨度 2.4 亿）→ 渲染视野改由图框并集决定
- matplotlib 等比坐标会覆盖手工 set_xlim/ylim → 世界→像素映射改为绘制后直接
  读 ax.transData（实际生效的变换），对 aspect 调整免疫
- 低 dpi 触发 FreeType "invalid ppem" 字体错误、ezdxf finalize 会重置画布尺寸
  （67.7×80in→4.4×4.8in）→ dpi 固定 100、像素直接定死、绘制后夺回 figsize
- 标题栏文字常藏在块定义里（模型空间 0 命中）→ 块内关键词文本 = 高置信信号

两重判定：
  通道A 矢量：a1 块插入（块名像图框 或 块内含标题栏关键词，且块内有图幅比例
             闭合框）＋ a2 模型空间闭合多段线（长宽比窗口筛）
  通道B 验证：b1 标题栏关键词文本（TEXT/MTEXT/ATTRIB）落入候选框
             b2 整图 PNG 跑 RapidOCR 的标题栏聚类估计（辅助/兜底）

融合：
  确认框 ≥2        → 按确认框精确坐标切片
  仅 a1 ≥2         → 命名/关键词块精度足够，直接切片
  仅 a2 ≥2         → 框内有文本密度（≥1 文本）才切片，防空框误检
  全 0             → 维持整图单页（= 现状，永不更糟），b2 有估计则记录供 AI 上下文
任何异常 → 退回整图单页，只记日志不阻断预处理。
"""
import logging
import math
import re
import time
from pathlib import Path

logger = logging.getLogger("app")

# ---- 矢量通道参数（与单位无关，只看长宽比）----
ASPECT_LO, ASPECT_HI = 1.28, 1.62       # ISO 图幅 √2≈1.414 为中心（含 A0+加长 ≈1.45）
RELAX_ASPECT_LO, RELAX_ASPECT_HI = 1.15, 1.90   # 放宽扫描（OCR 估计更多时触发）
MIN_SIDE = 20.0                          # 绝对下限只用来杀退化小框（单位无关）
FRAME_MAX_COUNT = 40                     # 单图图幅数上限（防误检爆炸）
CONTAINER_CHILDREN = 3                   # 某候选框包含 ≥3 个其他候选 → 判整图边界（丢弃）
NEST_EPS = 1e-6

# ---- 块名图框特征（命中即高置信，配合块内图幅框验证）----
FRAME_NAME_PAT = re.compile(
    r"(图框|图签|标题栏|边框|TITLE|FRAME)|^\s*A[0-4]\s*([x×*+]|$)", re.IGNORECASE)

# ---- 视觉通道：标题栏特征词（OCR 聚类 / 块内文本验证共用）----
TITLE_KEYWORDS = (
    "设计", "制图", "校核", "校对", "审核", "审定", "日期",
    "比例", "图号", "专业", "阶段", "会签", "负责人", "描图", "工种",
)

# ---- 切片渲染 ----
SLICE_PX_PER_UNIT = 6.5      # 切片画布目标精度（单位≈mm 时 ≈165dpi）
FRAME_MAX_EDGE = 4096        # 单帧长边像素上限（逐帧独立渲染，2026-09-25 起）
VIEW_PAD = 0.04              # 渲染视野 = 图框并集外扩 4%（仅 OCR 估计用）
FRAME_PAD = 0.008            # 单帧视野外扩比例（保住图框边线）


def _load_doc(dxf_path: str):
    import ezdxf
    from ezdxf import recover
    from services.drawing_service import patch_ezdxf_acis_tolerance
    patch_ezdxf_acis_tolerance()
    try:
        return ezdxf.readfile(dxf_path)
    except Exception:
        doc, _ = recover.readfile(dxf_path)
        return doc


def _rect_of(entity) -> tuple[float, float, float, float] | None:
    """实体世界坐标包围盒 (x0,y0,x1,y1)，失败返回 None"""
    from ezdxf import bbox as _bbox
    try:
        bb = _bbox.extents([entity], fast=True)
        if not bb.has_data:
            return None
        return (bb.extmin.x, bb.extmin.y, bb.extmax.x, bb.extmax.y)
    except Exception:
        return None


def _rect_ok(w: float, h: float, relaxed: bool) -> bool:
    """与单位无关的尺寸校验：退化下限 + 长宽比窗口（横竖放都算）"""
    if w <= 0 or h <= 0 or min(w, h) < MIN_SIDE:
        return False
    lo, hi = (RELAX_ASPECT_LO, RELAX_ASPECT_HI) if relaxed else (ASPECT_LO, ASPECT_HI)
    return lo <= max(w, h) / min(w, h) <= hi


def _inside(inner: tuple, outer: tuple) -> bool:
    return (inner[0] >= outer[0] - NEST_EPS and inner[1] >= outer[1] - NEST_EPS
            and inner[2] <= outer[2] + NEST_EPS and inner[3] <= outer[3] + NEST_EPS)


def _ent_text(e) -> str:
    try:
        if e.dxftype() == "MTEXT":
            return getattr(e, "text", "") or ""
        return e.dxf.text or ""
    except Exception:
        return ""


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _collect_poly_candidates(msp, relaxed: bool) -> list[tuple]:
    """通道 a2：模型空间闭合多段线（长宽比窗口；柱截面/格栅等 1.1x 比例的重复框全灭）"""
    cands = []
    for e in msp:
        try:
            t = e.dxftype()
            if t == "LWPOLYLINE":
                if not getattr(e, "closed", 0):
                    continue
            elif t == "POLYLINE":
                if not getattr(e, "is_closed", False):
                    continue
            else:
                continue
            r = _rect_of(e)
            if r and _rect_ok(r[2] - r[0], r[3] - r[1], relaxed):
                cands.append(r)
        except Exception:
            continue
    return cands


def _block_info(blk) -> tuple[tuple | None, bool]:
    """块定义内信息：最大闭合框(块坐标) + 是否含标题栏关键词。

    不做长宽比过滤——实测 A0+34 块的外框是 2081×841（带折边/加长，比例 2.47
    非 √2），块整体 bbox 又常被脏几何撑爆。图框是块内面积压倒性最大的闭合
    多段线（图签格子都是小不点），"最大闭合框"足够稳；长宽比放到世界坐标
    用宽窗口兜底（_FRAME_WORLD_HI）。
    """
    from ezdxf import bbox as _bbox
    frame = None
    has_kw = False
    for be in blk:
        try:
            t = be.dxftype()
        except Exception:
            continue
        if t in ("TEXT", "MTEXT", "ATTDEF"):
            if not has_kw and any(k in _norm(_ent_text(be)) for k in TITLE_KEYWORDS):
                has_kw = True
            continue
        if t not in ("LWPOLYLINE", "POLYLINE"):
            continue
        if not (getattr(be, "closed", 0) or getattr(be, "is_closed", False)):
            continue
        try:
            bb = _bbox.extents([be], fast=True)
            if not bb.has_data:
                continue
            w, h = bb.extmax.x - bb.extmin.x, bb.extmax.y - bb.extmin.y
            if min(w, h) <= 0:
                continue
            area = w * h
            if frame is None or area > frame[0]:
                frame = (area, (bb.extmin.x, bb.extmin.y, bb.extmax.x, bb.extmax.y))
        except Exception:
            continue
    return (frame[1] if frame else None), has_kw


# 块插入框世界坐标宽窗口：加长图幅比例可达 2.5+，以名字/关键词为准入信号
_FRAME_WORLD_LO, _FRAME_WORLD_HI = 1.05, 3.2


def _xform_rect(rc: tuple, ins) -> tuple | None:
    """块坐标矩形 → 插入矩阵（缩放→旋转→平移）→ 世界矩形"""
    try:
        a = math.radians(getattr(ins.dxf, "rotation", 0) or 0)
        c, s = math.cos(a), math.sin(a)
        sx = getattr(ins.dxf, "xscale", 1) or 1
        sy = getattr(ins.dxf, "yscale", 1) or 1
        tx, ty = ins.dxf.insert.x, ins.dxf.insert.y
    except Exception:
        return None
    xs, ys = [], []
    for x, y in ((rc[0], rc[1]), (rc[2], rc[1]), (rc[2], rc[3]), (rc[0], rc[3])):
        X, Y = x * sx, y * sy
        xs.append(X * c - Y * s + tx)
        ys.append(X * s + Y * c + ty)
    return (min(xs), min(ys), max(xs), max(ys))


def _insert_candidates(doc, msp) -> list[tuple]:
    """通道 a1：图幅级块插入。

    准入 = 块内有图幅比例闭合框（世界坐标变换后仍过主窗口）
           且（块名像图框 或 块内含标题栏关键词文本）
    """
    cache: dict[str, tuple] = {}
    out = []
    for e in msp:
        if e.dxftype() != "INSERT":
            continue
        try:
            name = e.dxf.name or ""
        except Exception:
            continue
        if name not in cache:
            blk = doc.blocks.get(name)
            cache[name] = _block_info(blk) if blk is not None else (None, False)
        bc, has_kw = cache[name]
        if bc is None:
            continue
        r = _xform_rect(bc, e)
        if not r:
            continue
        w, h = r[2] - r[0], r[3] - r[1]
        if min(w, h) < MIN_SIDE or not (_FRAME_WORLD_LO <= max(w, h) / min(w, h) <= _FRAME_WORLD_HI):
            continue
        if not (has_kw or FRAME_NAME_PAT.search(name)):
            continue
        out.append(r)
    return _nest_filter(out)


def _nest_filter(cands: list[tuple]) -> list[tuple]:
    """嵌套处理：面积降序贪心。
    - 含 ≥3 个其他候选的框 = 整图边界 → 丢弃（否则吞掉所有图幅）
    - 落在已保留框内部的 = 同框内边线 → 丢弃（只留外框）
    """
    uniq = sorted(set(cands), key=lambda r: -(r[2] - r[0]) * (r[3] - r[1]))
    kept: list[tuple] = []
    for i, c in enumerate(uniq):
        children = sum(1 for j, k in enumerate(uniq) if j != i and _inside(k, c))
        if children >= CONTAINER_CHILDREN:
            continue
        if any(_inside(c, k) for k in kept):
            continue
        kept.append(c)
        if len(kept) >= FRAME_MAX_COUNT:
            break
    return kept


def _vector_frames(msp, relaxed: bool = False) -> list[tuple]:
    return _nest_filter(_collect_poly_candidates(msp, relaxed))


def _merge_frames(primary: list[tuple], extra: list[tuple]) -> list[tuple]:
    """二次扫描结果并入：已有框内/重复的丢弃"""
    merged = list(primary)
    for e in extra:
        if any(_inside(e, k) or _inside(k, e) for k in merged):
            continue
        merged.append(e)
        if len(merged) >= FRAME_MAX_COUNT:
            break
    return merged


def _msp_text_points(msp) -> tuple[list[tuple], list[tuple]]:
    """模型空间文本位置点：(全部文本点, 标题栏关键词点)。ATTRIB 挂靠 INSERT 一并收。"""
    all_pts: list[tuple] = []
    kw_pts: list[tuple] = []
    for e in msp:
        t = e.dxftype()
        if t in ("TEXT", "MTEXT"):
            s = _norm(_ent_text(e))
            try:
                p = (e.dxf.insert.x, e.dxf.insert.y)
            except Exception:
                continue
            all_pts.append(p)
            if any(k in s for k in TITLE_KEYWORDS):
                kw_pts.append(p)
        elif t == "INSERT":
            for a in getattr(e, "attribs", ()):
                s = _norm(_ent_text(a))
                if not s:
                    continue
                try:
                    p = (a.dxf.insert.x, a.dxf.insert.y)
                except Exception:
                    continue
                all_pts.append(p)
                if any(k in s for k in TITLE_KEYWORDS):
                    kw_pts.append(p)
    return all_pts, kw_pts


def _ocr_estimate(png_path: str, r_px: float) -> int:
    """通道 b2：整图 PNG → RapidOCR → 标题栏特征词聚类 → 图框数估计"""
    try:
        from services.drawing_service import _get_ocr_engine
        result, _ = _get_ocr_engine()(str(png_path))
    except Exception:
        logger.warning("[图框检测] OCR 估计失败", exc_info=True)
        return 0
    hits = []
    for line in (result or []):
        try:
            box, text = line[0], line[1] or ""
            if any(k in _norm(text) for k in TITLE_KEYWORDS):
                hits.append(((box[0][0] + box[2][0]) / 2, (box[0][1] + box[2][1]) / 2))
        except Exception:
            continue
    # 贪心聚类：命中点落入已有簇半径内则归并，否则自立簇
    clusters: list[list[float]] = []  # [sum_x, sum_y, n]
    r2 = max(r_px, 8.0) ** 2
    for (x, y) in hits:
        best, best_d = None, None
        for c in clusters:
            cx, cy = c[0] / c[2], c[1] / c[2]
            d = (x - cx) ** 2 + (y - cy) ** 2
            if d <= r2 and (best_d is None or d < best_d):
                best, best_d = c, d
        if best is not None:
            best[0] += x
            best[1] += y
            best[2] += 1
        else:
            clusters.append([x, y, 1])
    return len(clusters)


def _cluster_radius_px(frames: list[tuple], content_w: float, png_w: float) -> float:
    """聚类半径：有矢量框时用最小框边的 0.45 折算 px；否则整图宽 12%"""
    if frames and content_w > 0:
        min_mm = min(min(f[2] - f[0], f[3] - f[1]) for f in frames)
        return 0.45 * min_mm * (png_w / content_w)
    return 0.12 * png_w


def _z_order(frames: list[tuple]) -> list[tuple]:
    """阅读序：上→下、左→右（世界 y 向上）"""
    return sorted(frames, key=lambda f: (-f[3], f[0]))


def _union_view(frames: list[tuple]) -> tuple[float, float, float, float]:
    """渲染视野 = 图框并集外扩 VIEW_PAD（躲开污染整图 extents 的脏几何）"""
    x0 = min(f[0] for f in frames)
    y0 = min(f[1] for f in frames)
    x1 = max(f[2] for f in frames)
    y1 = max(f[3] for f in frames)
    pw, ph = (x1 - x0) * VIEW_PAD, (y1 - y0) * VIEW_PAD
    return (x0 - pw, y0 - ph, x1 + pw, y1 + ph)


def _entity_boxes(msp) -> dict:
    """整图实体包围盒预计算（一次/图，fast 近似 + 块缓存）。
    求不出 bbox 的实体记 None → 渲染时保守放行，绝不因过滤丢内容。"""
    from ezdxf import bbox
    cache = bbox.Cache()
    boxes = {}
    for e in msp:
        try:
            b = bbox.extents([e], fast=True, cache=cache)
            boxes[id(e)] = b if b.has_data else None
        except Exception:
            boxes[id(e)] = None
    return boxes


def _render_frame(doc, frame: tuple, out_path: str, boxes: dict | None = None) -> bool:
    """单个图框独立画布渲染成 PNG（一帧一画布，分辨率不随图框数量摊薄）。

    世界→像素直接由视野尺寸 × SLICE_PX_PER_UNIT 决定，长边封顶 FRAME_MAX_EDGE。
    dpi 固定 100（低 dpi 触发 FreeType "invalid ppem"）；ezdxf finalize 会按内容
    范围重置画布尺寸，绘制后必须夺回 figsize。
    boxes 提供时按视野过滤实体（只画框内实体，密集大图逐帧渲染的耗时关键）。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy

    from services.chart_render.fonts import register_matplotlib
    register_matplotlib()
    from services.drawing_service import apply_cjk_fonts
    apply_cjk_fonts(doc)

    x0, y0, x1, y1 = frame
    vw, vh = x1 - x0, y1 - y0
    if vw <= 0 or vh <= 0:
        return False
    h_px = min(FRAME_MAX_EDGE, max(64, round(vh * SLICE_PX_PER_UNIT)))
    w_px = max(64, round(vw * (h_px / vh)))
    if max(w_px, h_px) > FRAME_MAX_EDGE:
        k = FRAME_MAX_EDGE / max(w_px, h_px)
        w_px, h_px = round(w_px * k), round(h_px * k)
    dpi = 100
    fig = plt.figure(figsize=(w_px / dpi, h_px / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()

    filter_func = None
    if boxes is not None:
        def filter_func(e, _b=boxes, _v=(x0, y0, x1, y1)):
            try:
                b = _b.get(id(e))
                if b is None:
                    return True  # 无 bbox → 保守绘制
                return not (b.extmax.x < _v[0] or b.extmin.x > _v[2]
                            or b.extmax.y < _v[1] or b.extmin.y > _v[3])
            except Exception:
                return True

    try:
        ctx = RenderContext(doc)
        backend = MatplotlibBackend(ax)
        cfg = Configuration(background_policy=BackgroundPolicy.WHITE,
                            color_policy=ColorPolicy.BLACK)
        Frontend(ctx, backend, config=cfg).draw_layout(
            doc.modelspace(), finalize=True, filter_func=filter_func)
        # finalize 会按内容范围重置画布尺寸（实测 67.7×80in → 4.4×4.8in），夺回
        fig.set_size_inches(w_px / dpi, h_px / dpi)
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        fig.canvas.draw()
        fig.savefig(out_path, dpi=dpi, facecolor="white")
        return True
    finally:
        plt.close(fig)


def _render_and_crop(doc, frames: list[tuple], out_stem: str,
                     view: tuple[float, float, float, float]) -> list[str]:
    """逐帧独立渲染切片（每帧一张画布）。

    2026-09-25 重构：旧实现把全部图框画进同一张 ≤8000px 长边的画布再按坐标裁剪，
    图框横向一多（如实测 7 列）每帧只剩 ~1088px，A0/1:150 平面图上 DJj 级标注
    不可读，模型被迫回退文本层脑补空间归属（办公楼 DJj03 误答 DJj08 事件）。
    view 参数（图框并集）仅为兼容旧签名保留，不再使用。
    """
    outs = []
    t0 = time.time()
    boxes = _entity_boxes(doc.modelspace())
    logger.info("[图框切片] 实体包围盒预计算 %d 个，%.1fs", len(boxes), time.time() - t0)
    for i, f in enumerate(frames, 1):
        fw, fh = f[2] - f[0], f[3] - f[1]
        if fw <= 0 or fh <= 0:
            continue
        px, py = fw * FRAME_PAD, fh * FRAME_PAD
        out = f"{out_stem}_p{i}.png"
        try:
            if _render_frame(doc, (f[0] - px, f[1] - py, f[2] + px, f[3] + py),
                             out, boxes):
                outs.append(out)
        except Exception as e:
            logger.warning("[图框切片] 第 %d 帧渲染失败（跳过）: %s", i, e)
    return outs


def detect_and_slice(dxf_path: str, overview_png: str, out_stem: str) -> dict:
    """两重判定 + 切片主入口。

    返回: {method, vector_count, ocr_count, frame_count, frames, slices}
    - method: none | ocr_est | vector | vector+ocr | error
    - slices 非空时调用方应把 image_count 置为 1 + len(slices)（首页=整图总览）
    任何异常内部消化并返回 slices=[]，绝不阻断预处理。
    """
    result = {"method": "none", "vector_count": 0, "ocr_count": 0,
              "frame_count": 0, "frames": [], "slices": []}
    try:
        doc = _load_doc(dxf_path)
        msp = doc.modelspace()

        # ---- 通道A：矢量（a1 块插入 + a2 闭合多段线）----
        a1 = _insert_candidates(doc, msp)
        a2 = _vector_frames(msp)
        frames = _merge_frames(a1, a2)
        result["vector_count"] = len(frames)

        # ---- 通道B：文本验证点 + 整图 OCR 估计 ----
        txt_pts, kw_pts = _msp_text_points(msp)
        m = 0
        overview = Path(overview_png)
        if overview.exists():
            from PIL import Image as _PIL
            with _PIL.open(overview) as im:
                png_w = im.size[0]
            content_w = max((f[2] - f[0] for f in frames), default=0)
            # 整图宽估计：用图框并集更稳（整图 extents 可能含脏几何）
            if frames:
                v = _union_view(frames)
                content_w = max(v[2] - v[0], content_w)
            r_px = _cluster_radius_px(frames, content_w, png_w)
            m = _ocr_estimate(str(overview), r_px)
        result["ocr_count"] = m

        a1_set = set(a1)
        confirmed = [f for f in frames
                     if f in a1_set or any(f[0] <= x <= f[2] and f[1] <= y <= f[3]
                                           for x, y in kw_pts)]

        if m > len(frames):
            # OCR 看到更多 → 疑似漏检（散线段画框），放宽二次扫描后重新融合
            frames = _merge_frames(frames, _vector_frames(msp, relaxed=True))
            confirmed = [f for f in frames
                         if f in a1_set or any(f[0] <= x <= f[2] and f[1] <= y <= f[3]
                                               for x, y in kw_pts)]

        # ---- 融合 ----
        targets, method = None, None
        if len(confirmed) >= 2:
            targets, method = confirmed, "vector"
            if m:
                method = "vector+ocr"
        elif len(a1) >= 2:
            # 命名/关键词块本身就是高置信（样图实测：块名 A0+34 + 块内标题词）
            targets, method = a1, "vector"
        elif len(frames) >= 2:
            # 纯多段线通道：用文本密度兜底（框内 ≥1 文本才认，防空框误检）
            dense = frames if not txt_pts else [
                f for f in frames
                if any(f[0] <= x <= f[2] and f[1] <= y <= f[3] for x, y in txt_pts)]
            if len(dense) >= 2:
                targets, method = dense, "vector"

        if not targets:
            if m >= 1:
                result["method"] = "ocr_est"
                result["frame_count"] = m
            logger.info("[图框检测] 无可切图幅（矢量=%d OCR估=%d）：%s",
                        len(frames), m, Path(dxf_path).name)
            return result

        targets = _z_order(targets)
        slices = _render_and_crop(doc, targets, out_stem, _union_view(targets))
        if not slices:
            result["method"] = "error"
            return result

        result.update({
            "method": method or "vector",
            "frames": targets,
            "frame_count": len(slices),
            "slices": slices,
        })
        logger.info("[图框检测] 切片完成 method=%s N=%d ocr估=%d：%s",
                    result["method"], len(slices), m, Path(dxf_path).name)
        return result
    except Exception:
        logger.exception("[图框检测] 异常，退回单页：%s", dxf_path)
        result["method"] = "error"
        return result
