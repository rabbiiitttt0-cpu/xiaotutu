"""Snip 局部放大定位工具（确定性，零 LLM）。

DJj03 归因实验（2026-09-26）：定位类问答失败根因是 VLM 内部降采样——4096px 整幅
喂入后角部小字不可读；"整幅 + 角部放大裁剪"是唯一成功臂。本模块把 LocateAgent 的
部位描述变成像素级裁剪图：

- 存量图纸（ctx 无 frame rect）：切片 OCR（磁盘缓存）→ 像素空间定位
- 新图纸（ctx 有 frames[].rect）：世界坐标直接映射切片像素，免 OCR 快路径

任何异常 → 返回空结果，绝不阻断问答主链路。
"""
import base64
import io
import json
import logging
import re
from pathlib import Path

from config import DATA_DIR

logger = logging.getLogger("app")

UPLOAD_DIR = DATA_DIR / "drawing_uploads"
OCR_CACHE_SUFFIX = ".ocr.json"
MIN_CROP_EDGE = 600    # 裁剪短边下限（px）
MAX_CROP_EDGE = 1600   # 裁剪长边上限（px）
UPSCALE_EDGE = 1200    # 裁剪图短边放大到该值（LANCZOS）
AXIS_CLUSTER_PX = 25   # 轴号标签同轴聚类半径（px）


# ==================== 切片/图纸文件 ====================

def slice_paths(file_id: str) -> dict[int, Path]:
    """{0: 整图总览, 1: p1切片, 2: p2, ...}（分块 _tRC 不算页）"""
    out: dict[int, Path] = {}
    hi = UPLOAD_DIR / f"{file_id}_hi.png"
    single = UPLOAD_DIR / f"{file_id}.png"
    if hi.exists():
        out[0] = hi
    elif single.exists():
        out[0] = single
    pat = re.compile(rf"^{re.escape(file_id)}_p(\d+)$")
    for p in UPLOAD_DIR.glob(f"{file_id}_p*.png"):
        m = pat.match(p.stem)
        if m:
            out[int(m.group(1))] = p
    return out


# ==================== OCR（磁盘缓存） ====================

def ocr_slice_cached(png_path: Path) -> list[dict]:
    """RapidOCR 切片识别，{png}.ocr.json 磁盘缓存（mtime 校验）。
    返回 [{text, box, score, cx, cy}]，坐标为像素。"""
    png = Path(png_path)
    cache = png.with_suffix(OCR_CACHE_SUFFIX)
    try:
        if cache.exists() and cache.stat().st_mtime >= png.stat().st_mtime:
            return json.loads(cache.read_text(encoding="utf-8")).get("items", [])
    except Exception:
        pass
    try:
        from services.drawing_service import _get_ocr_engine
        result, _ = _get_ocr_engine()(str(png))
    except Exception as e:
        logger.warning("[snip] OCR失败 %s: %s", png.name, e)
        return []
    items = []
    for line in (result or []):
        box, text, score = line[0], line[1], line[2]
        cx = (box[0][0] + box[2][0]) / 2
        cy = (box[0][1] + box[2][1]) / 2
        items.append({"text": text, "box": box, "score": float(score),
                      "cx": round(cx, 1), "cy": round(cy, 1)})
    try:
        cache.write_text(json.dumps({"mtime": png.stat().st_mtime, "items": items},
                                    ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return items


# ==================== 位置描述解析 =================

_DASH = "–—‐‑‒−﹣－"
_AXIS_TOKEN = re.compile(
    r"([A-Za-z]{1,2}[-–—](?:\d{1,2}|[A-Za-z]{1,2}))"   # B-8 / B-A
    r"|(\d{1,2})\s*轴"                                   # 8轴
    r"|(?<![A-Za-z0-9])([A-Za-z])\s*(?=轴)")             # A轴
_DIR_WORDS = {
    "左上": "左上", "右上": "右上", "左下": "左下", "右下": "右下",
    "左侧": "左", "左边": "左", "左部": "左",
    "右侧": "右", "右边": "右", "右部": "右",
    "上方": "上", "上部": "上", "顶部": "上",
    "下方": "下", "下部": "下", "底部": "下",
    "中部": "中", "中间": "中", "中央": "中",
    "角部": "角", "角落": "角",
}


def normalize_axis(tok: str) -> str:
    """轴号归一化：取最后一个 - 后段并大写（"B-8"→"8"，OCR误识"8-8"→"8"）"""
    t = tok.strip().upper()
    for d in _DASH:
        t = t.replace(d, "-")
    if "-" in t:
        t = t.split("-")[-1]
    return t


def parse_location_spec(question: str) -> dict:
    """从问题中解析位置线索：轴号（原文+归一化）/方位词。供 target 补缺与单测。"""
    axes, seen = [], set()
    for m in _AXIS_TOKEN.finditer(question or ""):
        raw = next(g for g in m.groups() if g)
        norm = normalize_axis(raw)
        if norm and norm not in seen:
            seen.add(norm)
            axes.append({"raw": raw, "norm": norm})
    directions = []
    for w, code in _DIR_WORDS.items():
        if w in (question or "") and code not in directions:
            directions.append(code)
    return {"axes": axes, "directions": directions}


# ==================== 轴网几何 ====================

def _cluster_1d(vals: list[float], radius: float = AXIS_CLUSTER_PX) -> list[float]:
    """一维聚类，返回各簇中心（排序）"""
    if not vals:
        return []
    vals = sorted(vals)
    clusters, cur = [], [vals[0]]
    for v in vals[1:]:
        if v - cur[-1] <= radius:
            cur.append(v)
        else:
            clusters.append(sum(cur) / len(cur))
            cur = [v]
    clusters.append(sum(cur) / len(cur))
    return clusters


def _median_spacing(centers: list[float]) -> float:
    if len(centers) < 2:
        return 0.0
    gaps = sorted(b - a for a, b in zip(centers, centers[1:]))
    return gaps[len(gaps) // 2]


def find_axis_intersection(items: list[dict], axes: list[str]) -> dict | None:
    """轴号交点像素定位。axes 为归一化目标（如 ["8","A"]）。

    数字轴 → 列（x 聚类）；字母轴 → 行（y 聚类）。标签在轴线两端同名同坐标，
    取簇中心即轴线位置。目标轴缺失时按其他轴的等距外推。
    返回 {x, y, col_spacing, row_spacing}（px）或 None。"""
    col_target = next((a for a in axes if a.isdigit()), None)
    row_target = next((a for a in axes if a.isalpha()), None)
    if not col_target and not row_target:
        return None

    col_hits: dict[str, list[float]] = {}
    row_hits: dict[str, list[float]] = {}
    for it in items:
        norm = normalize_axis(it.get("text") or "")
        if not norm or len(norm) > 3:
            continue
        if norm.isdigit() and len(norm) <= 2:
            col_hits.setdefault(norm, []).append(it["cx"])
        elif norm.isalpha() and len(norm) == 1:
            row_hits.setdefault(norm, []).append(it["cy"])

    def _pick(hits: dict, target: str | None) -> float | None:
        if target and target in hits and hits[target]:
            c = _cluster_1d(hits[target])
            return c[0] if c else None
        return None

    col_x = _pick(col_hits, col_target)
    row_y = _pick(row_hits, row_target)

    # 缺失轴按等距外推/内插：最近两已知轴的像素步长 × 序号差
    def _extrapolate(centers_map: dict[str, list[float]], target: str,
                     cluster_fn) -> float | None:
        if not target or not target.isdigit():
            return None
        pts = []
        for k, vals in centers_map.items():
            if not k.isdigit():
                continue
            cs = cluster_fn(vals)
            if cs:
                pts.append((int(k), cs[0]))
        if len(pts) < 2:
            return None
        pts.sort()
        keys = [k for k, _ in pts]
        t = int(target)
        if t in keys:
            return pts[keys.index(t)][1]
        import bisect
        i = bisect.bisect_left(keys, t)
        if i == 0:
            (k0, p0), (k1, p1) = pts[0], pts[1]
        elif i >= len(pts):
            (k0, p0), (k1, p1) = pts[-2], pts[-1]
        else:
            (k0, p0), (k1, p1) = pts[i - 1], pts[i]
        step = (p1 - p0) / (k1 - k0)
        return p0 + step * (t - k0)

    if col_x is None and col_target:
        col_x = _extrapolate(col_hits, col_target, _cluster_1d)

    if col_x is None and row_y is None:
        return None
    # 单边缺失时退化为轴带中部
    return {
        "x": col_x if col_x is not None else None,
        "y": row_y if row_y is not None else None,
        "col_spacing": _median_spacing(sorted(_cluster_1d(sum(col_hits.values(), [])))),
        "row_spacing": _median_spacing(sorted(_cluster_1d(sum(row_hits.values(), [])))),
    }


# ==================== 区域查找 =================

def find_table_region(items: list[dict], keywords: list[str]) -> tuple | None:
    """关键词命中点密度聚簇 → 表格/详图区域框 (x0,y0,x1,y1) px。"""
    kws = [k for k in (keywords or []) if k]
    if not kws:
        return None
    hits = [it for it in items
            if any(k.lower() in (it.get("text") or "").lower() for k in kws)]
    if not hits:
        return None
    if len(hits) == 1:
        h = hits[0]
        return (h["cx"] - 300, h["cy"] - 200, h["cx"] + 300, h["cy"] + 200)
    # 贪心聚簇：从命中点质心出发，吸收距当前框 400px 内的点
    cx = sum(h["cx"] for h in hits) / len(hits)
    cy = sum(h["cy"] for h in hits) / len(hits)
    hits.sort(key=lambda h: (h["cx"] - cx) ** 2 + (h["cy"] - cy) ** 2)
    box = [hits[0]["cx"], hits[0]["cy"], hits[0]["cx"], hits[0]["cy"]]
    for h in hits[1:]:
        if (box[0] - 400 <= h["cx"] <= box[2] + 400
                and box[1] - 400 <= h["cy"] <= box[3] + 400):
            box[0] = min(box[0], h["cx"])
            box[1] = min(box[1], h["cy"])
            box[2] = max(box[2], h["cx"])
            box[3] = max(box[3], h["cy"])
    pad = 80
    return (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)


_DIR_BOX = {
    "左上": (0.0, 0.0, 0.5, 0.5), "右上": (0.5, 0.0, 1.0, 0.5),
    "左下": (0.0, 0.5, 0.5, 1.0), "右下": (0.5, 0.5, 1.0, 1.0),
    "左": (0.0, 0.15, 0.45, 0.85), "右": (0.55, 0.15, 1.0, 0.85),
    "上": (0.15, 0.0, 0.85, 0.45), "下": (0.15, 0.55, 0.85, 1.0),
    "中": (0.25, 0.25, 0.75, 0.75), "角": (0.55, 0.45, 1.0, 1.0),
}


def direction_box(region: str, img_w: int, img_h: int) -> tuple | None:
    frac = _DIR_BOX.get((region or "").strip())
    if not frac:
        return None
    return (frac[0] * img_w, frac[1] * img_h, frac[2] * img_w, frac[3] * img_h)


# ==================== 按图幅文字摘要（对比型问题的核心） ====================

def frame_text_digest(file_id: str, frame_idx: int, info: dict,
                      budget: int = 1500) -> str:
    """按图幅分组的标注摘要：新图纸用 frames[].rect 做世界坐标归属判定；
    存量图纸用切片 OCR 文本去重聚合（缓存复用）。输出 "文字（×n）" 去重计数。"""
    texts: list[str] = []
    frames = info.get("frames") or []
    rect = None
    if 1 <= frame_idx <= len(frames):
        rect = (frames[frame_idx - 1] or {}).get("rect")
    if rect:
        x0, y0, x1, y1 = rect
        pad_x, pad_y = (x1 - x0) * 0.02, (y1 - y0) * 0.02
        for a in info.get("text_annotations") or []:
            pos = a.get("position")
            t = (a.get("text") or "").strip()
            if not t or not pos:
                continue
            if x0 - pad_x <= pos[0] <= x1 + pad_x and y0 - pad_y <= pos[1] <= y1 + pad_y:
                texts.append(t)
    else:
        png = slice_paths(file_id).get(frame_idx)
        if png:
            texts = [(it.get("text") or "").strip()
                     for it in ocr_slice_cached(png) if (it.get("text") or "").strip()]
    if not texts:
        return ""
    counts: dict[str, int] = {}
    order: list[str] = []
    for t in texts:
        if t not in counts:
            counts[t] = 0
            order.append(t)
        counts[t] += 1
    order.sort(key=lambda t: -counts[t])
    parts, used = [], 0
    for t in order:
        piece = f"{t}（×{counts[t]}）" if counts[t] > 1 else t
        if parts and used + len(piece) > budget:
            break
        parts.append(piece)
        used += len(piece)
    omitted = len(order) - len(parts)
    if omitted > 0:
        parts.append(f"…另{omitted}种未列出")
    return "；".join(parts)


# ==================== 裁剪 ====================

def make_crop(png_path: Path, box: tuple) -> bytes | None:
    """按像素框裁剪，clamp 到图像范围；短边放大至 ≥1200px（LANCZOS）。返回 PNG bytes。"""
    try:
        from PIL import Image
        im = Image.open(png_path).convert("RGB")
        w, h = im.size
        x0, y0, x1, y1 = box
        bw, bh = x1 - x0, y1 - y0
        # 边长 clamp [600, 1600]，中心不变
        side = max(bw, bh)
        side = max(MIN_CROP_EDGE, min(MAX_CROP_EDGE, side))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rx, ry = side / 2, side / 2 * (bh / bw if bw else 1)
        rx = min(rx, side / 2)
        ry = min(ry, side / 2)
        x0, x1 = max(0, cx - rx), min(w, cx + rx)
        y0, y1 = max(0, cy - ry), min(h, cy + ry)
        if x1 - x0 < 50 or y1 - y0 < 50:
            return None
        crop = im.crop((round(x0), round(y0), round(x1), round(y1)))
        if min(crop.size) < UPSCALE_EDGE:
            k = UPSCALE_EDGE / min(crop.size)
            crop = crop.resize((round(crop.size[0] * k), round(crop.size[1] * k)),
                               Image.LANCZOS)
        buf = io.BytesIO()
        crop.save(buf, "PNG")
        return buf.getvalue()
    except Exception as e:
        logger.warning("[snip] 裁剪失败 %s: %s", png_path, e)
        return None


# ==================== 生料包组装 ====================

def build_payload(selections: list[dict], info_by_fid: dict[str, dict],
                  question: str, max_images: int = 8) -> dict:
    """LocateAgent 结论 → 生料包 {images:[{b64,note}], texts:[], used_frames:[]}

    axis/table/region/keyword → 部位裁剪（A5 实验：整幅切片 + 部位裁剪成对出现，
    裁剪在前整幅在后，VLM 先在放大图读数、再回整幅确认空间关系）；
    frame → 整幅切片 + 按图幅文字摘要（对比型问题）。
    全程 try/except，失败部位静默跳过。"""
    entries: list[dict] = []   # 有序：{"crop"|"slice", b64, note}
    texts: list[str] = []
    used_frames: list[tuple] = []
    spec = parse_location_spec(question)

    for sel in selections:
        fid = sel.get("file_id", "")
        info = info_by_fid.get(fid) or {}
        filename = info.get("filename") or fid
        paths = slice_paths(fid)
        for fr in sel.get("frames") or []:
            idx = fr.get("frame_index", 0)
            title = fr.get("frame_title") or ""
            label = f"{filename} 图幅p{idx}" + (f"（{title}）" if title else "")
            png = paths.get(idx)
            targets = fr.get("targets") or []
            if not png:
                continue
            if not targets:
                entries.append({"kind": "slice", "png": png, "note": f"{label} 整幅"})
                used_frames.append((fid, idx))
                continue
            crops: list[dict] = []
            has_frame_target = False
            for t in targets:
                ttype = t.get("type")
                purpose = t.get("purpose") or ""
                try:
                    if ttype == "frame":
                        has_frame_target = True
                        digest = frame_text_digest(fid, idx, info)
                        if digest:
                            texts.append(f"【{label} 文字摘要】{digest}")
                        used_frames.append((fid, idx))
                    elif ttype == "axis":
                        axes = [normalize_axis(a) for a in (t.get("axes") or [])]
                        if not axes:
                            axes = [a["norm"] for a in spec["axes"]]
                        items = ocr_slice_cached(png)
                        inter = find_axis_intersection(items, axes)
                        if inter:
                            from PIL import Image
                            with Image.open(png) as im:
                                iw, ih = im.size
                            sp = inter["col_spacing"] or inter["row_spacing"] or 800
                            half = min(0.75 * sp, MAX_CROP_EDGE / 2)
                            cx = inter["x"] if inter["x"] is not None else iw / 2
                            cy = inter["y"] if inter["y"] is not None else ih / 2
                            data = make_crop(png, (cx - half, cy - half,
                                                   cx + half, cy + half))
                            if data:
                                crops.append({"b64": base64.b64encode(data).decode("ascii"),
                                              "note": f"{label} "
                                                      f"{'×'.join(t.get('axes') or axes)}"
                                                      f"交点附近放大（{purpose}）"})
                    elif ttype in ("table", "keyword"):
                        items = ocr_slice_cached(png)
                        box = find_table_region(items, t.get("keywords") or [])
                        data = make_crop(png, box) if box else None
                        if data:
                            crops.append({"b64": base64.b64encode(data).decode("ascii"),
                                          "note": f"{label} "
                                                  f"「{'/'.join((t.get('keywords') or [])[:3])}」"
                                                  f"相关区域放大（{purpose}）"})
                    elif ttype == "region":
                        from PIL import Image
                        with Image.open(png) as im:
                            iw, ih = im.size
                        box = direction_box(t.get("region") or "", iw, ih)
                        data = make_crop(png, box) if box else None
                        if data:
                            crops.append({"b64": base64.b64encode(data).decode("ascii"),
                                          "note": f"{label} {t.get('region')}区域放大"
                                                  f"（{purpose}）"})
                except Exception:
                    logger.exception("[snip] target处理失败 fid=%s p%s", fid, idx)
            if has_frame_target:
                entries.append({"kind": "slice", "png": png,
                                "note": f"{label} 整幅（{targets[0].get('purpose') or '整幅对照'}）"})
            elif crops:
                entries.extend({"kind": "crop", **c} for c in crops)
                entries.append({"kind": "slice", "png": png,
                                "note": f"{label} 整幅（定位参照）"})
                used_frames.append((fid, idx))
            else:
                entries.append({"kind": "slice", "png": png,
                                "note": f"{label} 整幅（部位定位失败，请自行查找）"})
                used_frames.append((fid, idx))

    images: list[dict] = []
    for e in entries[:max_images]:
        if "b64" in e:
            images.append({"b64": e["b64"], "note": e["note"]})
        else:
            try:
                images.append({"b64": base64.b64encode(e["png"].read_bytes()).decode("ascii"),
                               "note": e["note"]})
            except OSError:
                pass
    return {"images": images, "texts": texts, "used_frames": used_frames}
