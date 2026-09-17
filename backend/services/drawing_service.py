"""DXF图纸解析服务"""
import json
import platform
import subprocess
from pathlib import Path

import ezdxf
from ezdxf import recover
from ezdxf.tools import crypt as _crypt

_LIBREDWG_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "bin" / "libredwg"


def _crypt_decode_safe(text_lines):
    """ezdxf 原生 crypt.decode 内部 bytes(text, 'ascii')，LibreDWG 转出的 DXF
    里 ACIS SAT 段混入中文（如「云中心建筑图」）直接 UnicodeEncodeError 让整份
    图纸解析失败。这里复制官方实现，仅把 ascii 换成 latin-1（值域一一对应，
    高位字节按 chr(c ^ 0x5F) 原样处理，绝不抛异常）。"""
    def _decode(text):
        dectab = _crypt._decode_table
        s = []
        text = text.encode("latin-1", errors="ignore")
        skip = False
        for c in text:
            if skip:
                skip = False
                continue
            if c in dectab:
                s += dectab[c]
                skip = (c == 0x5E)
            else:
                s += chr(c ^ 0x5F)
        return "".join(s)
    return (_decode(line) for line in text_lines)


if getattr(_crypt.decode, "__name__", "") != "_crypt_decode_safe":
    _crypt.decode = _crypt_decode_safe


def convert_dwg_to_dxf(dwg_path: str, dxf_path: str) -> tuple[bool, str]:
    """DWG → DXF 转换。优先级链：ODA File Converter（本机装了就用，最可靠）
    → LibreDWG（仓库内置，永远兜底）。返回 (成功, 途径/错误信息)。

    选型（2026-09-14 王涛拍板 ②为主+①可选）：ODA 可靠性最高但闭源禁再分发、
    容器化脏，不作为硬依赖；LibreDWG GPL 单文件进仓库，任何环境开箱即用。
    """
    # 1) ODA File Converter（ezdxf odafc 插件自动探测标准安装路径，装了自动优先）
    try:
        from ezdxf.addons import odafc
        odafc.convert(dwg_path, dxf_path, replace=True)
        if Path(dxf_path).exists():
            return True, "ODA File Converter"
    except Exception:
        pass
    # 2) LibreDWG（assets/bin/libredwg/{win,linux}，随仓库分发）
    exe = _LIBREDWG_DIR / ("win/dwg2dxf.exe" if platform.system() == "Windows" else "linux/dwg2dxf")
    if exe.exists():
        try:
            r = subprocess.run(
                [str(exe), "-y", "-o", dxf_path, dwg_path],
                capture_output=True, timeout=180,
                encoding="utf-8", errors="ignore",
            )
            out = Path(dxf_path)
            if out.exists() and out.stat().st_size > 0:
                return True, "LibreDWG"
            return False, f"LibreDWG 转换失败: {(r.stderr or r.stdout or '')[-300:]}"
        except Exception as e:
            return False, f"LibreDWG 调用失败: {e}"
    return False, "DWG 转换器不可用（LibreDWG 缺失且未安装 ODA File Converter）"


def clean_text(s: str) -> str:
    """剔除孤立的 UTF-16 代理对（DWG 常见坏编码），否则落盘/送 LLM 时 utf-8 编码炸"""
    if not s:
        return s
    return "".join(c for c in s if not (0xD800 <= ord(c) <= 0xDFFF))


def parse_dxf(file_path: str, display_name: str | None = None) -> dict:
    """解析DXF文件，提取图纸信息。display_name：展示用原始文件名
    （上传场景文件以 file_id 落盘，不传则描述里全是内部名 dxf_xxx.dxf）"""
    path = Path(file_path)
    shown_name = display_name or path.name

    try:
        doc = ezdxf.readfile(file_path)
    except Exception:
        try:
            doc, auditor = recover.readfile(file_path)
        except Exception as e:
            raise RuntimeError(f"无法解析DXF文件: {e}")

    msp = doc.modelspace()

    # 图层信息（ezdxf 的 is_on/is_locked 是方法不是属性，漏括号会存成绑定方法：
    # description 显示 <bound method ...> 且 JSON 序列化直接炸）
    layers = []
    for layer in doc.layers:
        layers.append({
            "name": layer.dxf.name,
            "color": layer.dxf.color,
            "is_on": layer.is_on(),
            "is_locked": layer.is_locked(),
        })

    # 实体统计
    entity_counts = {}
    entities_detail = []
    text_annotations = []

    for entity in msp:
        etype = entity.dxftype()
        entity_counts[etype] = entity_counts.get(etype, 0) + 1

        # 收集文字标注
        if etype == "TEXT":
            try:
                text_annotations.append({
                    "text": clean_text(entity.dxf.text),
                    "layer": entity.dxf.layer,
                    "position": [entity.dxf.insert.x, entity.dxf.insert.y],
                })
            except Exception:
                pass
        elif etype == "MTEXT":
            try:
                text_annotations.append({
                    "text": clean_text(entity.plain_text()),
                    "layer": entity.dxf.layer,
                    "position": [entity.dxf.insert.x, entity.dxf.insert.y],
                })
            except Exception:
                pass
        elif etype == "INSERT":
            # 块内文字展开（virtual_entities 已做 WCS 坐标变换）——
            # 构件大样/图签常做在块里，不展开则块内文字整体丢失
            try:
                for ve in entity.virtual_entities():
                    vtype = ve.dxftype()
                    if vtype == "TEXT":
                        text_annotations.append({
                            "text": clean_text(ve.dxf.text),
                            "layer": ve.dxf.layer,
                            "position": [ve.dxf.insert.x, ve.dxf.insert.y],
                            "from_block": entity.dxf.name,
                        })
                    elif vtype == "MTEXT":
                        text_annotations.append({
                            "text": clean_text(ve.plain_text()),
                            "layer": ve.dxf.layer,
                            "position": [ve.dxf.insert.x, ve.dxf.insert.y],
                            "from_block": entity.dxf.name,
                        })
            except Exception:
                pass  # 单个块展开失败不影响整体

    # 块定义
    blocks = []
    for block in doc.blocks:
        if not block.name.startswith("*"):
            block_entities = list(block)
            blocks.append({
                "name": block.name,
                "entity_count": len(block_entities),
            })

    # 生成结构化文本描述（供LLM理解）
    description = _generate_description(shown_name, layers, entity_counts, text_annotations, blocks)

    return {
        "filename": shown_name,
        "layers": layers,
        "layer_count": len(layers),
        "entity_counts": entity_counts,
        "total_entities": sum(entity_counts.values()),
        "text_annotations": text_annotations,  # 全量存储（不再截断），注入由 description 分层控制
        "blocks": blocks,
        "description": description,
    }


# 图框文字内容判据（替代坐标判定——坐标包围盒随图变化极易误判，2026-09-15 王涛指出）：
# 图框标题栏的文字说的是"图框话"（图号/比例/日期/单位/人员/版本），与位置无关
import re as _re

_TB_STRONG = _re.compile(
    r"(图号|图名|图纸编号|档案号|建设单位|设计单位|工程名称|项目名称|施工单位|监理单位"
    r"|制图|绘图|校对|审核|审定|会签|项目负责人|专业负责|资质|出图|注册|版次|版本|阶段"
    r"|1\s*[:：]\s*\d{2,4}"                # 比例 1:100 / 1：500
    r"|20\d{2}\s*[年./\-]\s*\d{1,2}"       # 日期 2025.12 / 2025年12月
    r")")
_TB_DRAWING_NO = _re.compile(r"^[A-Za-z0-9]+([-–—][A-Za-z0-9]+){2,}$")  # 图号样式 18164-S-011-SJ-JK-007
_TB_TITLE_SUFFIX = _re.compile(
    r"(布置图|结构图|平面图|剖面图|纵剖面图|横剖面图|详图|大样图|示意图|系统图|断面图"
    r"|配筋图|模板图|安装图|节点图|总平面图|施工图|竣工图)$")


def _looks_title_block(text: str) -> bool:
    """判断是否图框标题栏文字（内容判据，不用坐标）"""
    t = text.strip()
    if not t or len(t) > 40:
        return False
    if _TB_STRONG.search(t):
        return True
    if _TB_DRAWING_NO.match(t):
        return True
    if len(t) <= 25 and _TB_TITLE_SUFFIX.search(t):
        return True
    return False


def _format_annotations_block(text_annotations: list[dict], budget: int = 6000) -> list[str]:
    """文字标注分层注入（2026-09-15 王涛拍板，替代原'前50条'硬截断）：
    ① 相同文字合并计数（Φ8@200×47）——工程图纸通常压缩5~10倍，多数图可全量注入
    ② 右下角图框区域标注永远优先（图名/图号/说明信息密度最高）
    ③ 仍超预算则截断并如实标注遗漏数，不让模型假装看全了
    """
    if not text_annotations:
        return []

    # 图框判定改用内容模式（标题栏文字说的是"图框话"），坐标判定已废弃
    def _in_title_block(t) -> bool:
        return _looks_title_block(t.get("text") or "")

    # 去重保序聚合
    agg: dict[str, dict] = {}
    order: list[str] = []
    for t in text_annotations:
        key = (t.get("text") or "").strip()
        if not key:
            continue
        if key not in agg:
            agg[key] = {"n": 0, "tb": False, "layer": t.get("layer", "")}
            order.append(key)
        agg[key]["n"] += 1
        if _in_title_block(t):
            agg[key]["tb"] = True

    total_raw = sum(a["n"] for a in agg.values())
    lines = [f"## 文字标注（原始 {total_raw} 条，去重后 {len(order)} 种；[图框]=标题栏区域，优先注入）"]
    used = 0
    included = 0
    tb_keys = [k for k in order if agg[k]["tb"]]
    other_keys = [k for k in order if not agg[k]["tb"]]
    for k in tb_keys + other_keys:
        a = agg[k]
        text = f"{k}（×{a['n']}）" if a["n"] > 1 else k
        line = f"- {'[图框] ' if a['tb'] else ''}[{a['layer']}] {text}"
        if included and used + len(line) > budget:
            break
        lines.append(line)
        used += len(line)
        included += 1
    omitted = len(order) - included
    if omitted > 0:
        lines.append(f"- …另有 {omitted} 种标注因篇幅未注入（可按问题检索补充）")
    return lines


def _generate_description(filename, layers, entity_counts, text_annotations, blocks):
    """生成图纸的结构化文本描述"""
    lines = [
        f"# DXF图纸分析: {filename}",
        "",
        "## 图层列表",
    ]
    for layer in layers:
        status = "开启" if layer["is_on"] else "关闭"
        lock = "锁定" if layer["is_locked"] else "未锁定"
        lines.append(f"- {layer['name']}: 颜色={layer['color']}, 状态={status}, {lock}")

    lines.append("")
    lines.append("## 实体统计")
    for etype, count in sorted(entity_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- {etype}: {count}个")

    lines.append(f"- 总计: {sum(entity_counts.values())}个实体")

    if blocks:
        lines.append("")
        lines.append("## 块定义")
        for b in blocks[:20]:
            lines.append(f"- {b['name']}: {b['entity_count']}个实体")

    if text_annotations:
        lines.append("")
        lines.extend(_format_annotations_block(text_annotations))

    return "\n".join(lines)


def render_dxf_png(file_path: str, out_path: str, dpi: int = 160) -> str | None:
    """把 DXF 模型空间渲染为 PNG（白底黑线，供视觉模型识图）。
    同时尝试输出 SVG 矢量图（文字转曲线路径，浏览器预览无限放大不糊），
    返回 PNG 路径；SVG 结果存于同名 .svg（失败仅无 SVG，不影响 PNG）。

    用 ezdxf 自带 drawing 插件（matplotlib 后端），零新依赖；
    中文标注走 chart_render 的内置思源黑体注册。失败返回 None（不阻断上传流程）。
    """
    try:
        from services.chart_render.fonts import register_matplotlib
        register_matplotlib()
        import matplotlib.pyplot as plt
        from ezdxf.addons.drawing import RenderContext, Frontend
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy

        try:
            doc = ezdxf.readfile(file_path)
        except Exception:
            doc, _ = recover.readfile(file_path)
        msp = doc.modelspace()

        # 中文字形：把内置 CJK 字体注册给 ezdxf 字体管理器，并将文字样式统一
        # 映射到内置 TTF——DXF 默认 SHX 字体（txt/gbcbig/hztxt.shx）无字形文件时
        # 中文会渲染成方框（fallback ARIALUNI.TTF 一般不存在）
        # 优先用工程扩展子集（含 Φ×²³± 等图纸符号），缺文件回退交底图表子集
        from services.chart_render.fonts import FONT_PATH as CHART_FONT
        from ezdxf import options as ez_options
        from ezdxf.fonts import fonts as ez_fonts
        eng_font = CHART_FONT.parent / "NotoSansSC-eng-subset.otf"
        font_file = eng_font if eng_font.exists() else CHART_FONT
        if font_file.exists():
            font_dir = str(font_file.parent)
            if font_dir not in ez_options.support_dirs:
                ez_options.support_dirs.append(font_dir)
            try:
                ez_fonts.font_manager.scan_folder(font_file.parent)
            except Exception:
                pass
            for style in doc.styles:
                try:
                    style.dxf.font = font_file.name
                except Exception:
                    pass

        fig = plt.figure(figsize=(12, 12))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_axis_off()
        ctx = RenderContext(doc)
        backend = MatplotlibBackend(ax)
        # 白底黑线：视觉模型与人工预览都可读性最好
        cfg = Configuration(
            background_policy=BackgroundPolicy.WHITE,
            color_policy=ColorPolicy.BLACK,
        )
        Frontend(ctx, backend, config=cfg).draw_layout(msp, finalize=True)
        fig.savefig(out_path, dpi=dpi, facecolor="white")
        # SVG 矢量预览（文字转曲线路径 svg.fonttype='path'，无客户端字体依赖）。
        # 真实大图纸 SVG 可达百MB级（实测8MB DXF→116MB SVG，浏览器必卡死）：
        # >25MB 放弃 SVG，改出 400dpi 高清 PNG 作预览（放大清晰度约2.5倍于默认160dpi）
        try:
            import matplotlib as _mpl
            _mpl.rcParams["svg.fonttype"] = "path"
            svg_path = out_path.rsplit(".", 1)[0] + ".svg"
            fig.savefig(svg_path, format="svg", facecolor="white")
            if Path(svg_path).stat().st_size > 25 * 1024 * 1024:
                Path(svg_path).unlink(missing_ok=True)
                # 高清兜底：ezdxf finalize 会按内容宽高比重置画布，默认160dpi常只有
                # 640~1900px（放大即糊的元凶）——按长边4800px反推dpi（300~1200钳制）
                w_in, h_in = fig.get_size_inches()
                hi_dpi = int(min(1200, max(300, 4800 / max(w_in, h_in, 0.1))))
                fig.savefig(out_path.rsplit(".", 1)[0] + "_hi.png", dpi=hi_dpi, facecolor="white")
        except Exception:
            pass
        plt.close(fig)
        return out_path
    except Exception:
        import traceback
        traceback.print_exc()  # 渲染失败须留痕（静默丢图曾是痛点），不阻断上传
        try:
            plt.close("all")  # noqa
        except Exception:
            pass
        return None


# ==================== PDF 图纸支持（2026-09-14：设计院交付物以 PDF 为主） ====================

PDF_MAX_PAGES = 3        # 单份 PDF 最多取前 3 页（视觉问答带图上限，控制 token 成本）
PDF_RENDER_DPI = 180     # A1 图纸约 5900x4200px，兼顾标注可读性与 PNG 体积
PDF_TEXT_MAX = 8000      # 注入 prompt 的文本总量上限
OCR_DPI = 150            # 本地 OCR 渲染精度（无文字层时补文字层，KB 同款 RapidOCR）
OCR_TEXT_MAX = 8000      # OCR 文本注入上限
# 密集小字判定：OCR 文本框数量与框高中位数双阈值（触发分块渲染）
DENSE_BOX_COUNT = 100
DENSE_MEDIAN_H_PX = 40   # 180dpi 下附注级小字约 25~40px


def _ai_cfg() -> dict:
    """AI识图运行时配置（系统设置→Agent设置→AI识图，可调；常量为兜底默认值）"""
    try:
        from config import load_config
        s = load_config().agent_settings
        return {
            "tile_enabled": getattr(s, "drawing_tile_enabled", True),
            "max_pages": getattr(s, "drawing_pdf_max_pages", PDF_MAX_PAGES),
            "text_max": getattr(s, "drawing_pdf_text_max", PDF_TEXT_MAX),
            "ocr_dpi": getattr(s, "drawing_ocr_dpi", OCR_DPI),
            "ocr_text_max": getattr(s, "drawing_ocr_text_max", OCR_TEXT_MAX),
        }
    except Exception:
        return {"tile_enabled": True, "max_pages": PDF_MAX_PAGES,
                "text_max": PDF_TEXT_MAX, "ocr_dpi": OCR_DPI, "ocr_text_max": OCR_TEXT_MAX}


def _ocr_page_image(page, dpi: int = OCR_DPI) -> tuple[list, int]:
    """单页渲染灰度图送 RapidOCR，返回(行列表[(text,box_h,cx,cy)], 页高px)"""
    from rapidocr_onnxruntime import RapidOCR
    import tempfile
    from pathlib import Path as _P
    pix = page.get_pixmap(matrix=__import__("fitz").Matrix(dpi / 72, dpi / 72))
    with tempfile.TemporaryDirectory() as tmp:
        img = str(_P(tmp) / "p.png")
        pix.save(img)
        result, _ = _get_ocr_engine()(img)
    rows = []
    for line in (result or []):
        box, text, score = line[0], line[1], line[2]
        h = abs(box[3][1] - box[0][1])
        cx = (box[0][0] + box[2][0]) / 2
        cy = (box[0][1] + box[2][1]) / 2
        rows.append((text, h, cx, cy))
    return rows, pix.height


_ocr_engine = None


def _get_ocr_engine():
    """RapidOCR 引擎单例（模型加载慢，勿每次新建）"""
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
    return _ocr_engine


def parse_pdf_drawing(file_path: str, display_name: str | None = None) -> dict:
    """解析 PDF 图纸：提取页数与矢量文字层全文，生成 LLM 用 description。

    矢量 PDF 图纸自带文字层（设计院直接打印的 PDF），文字提取即得标注信息；
    扫描版 PDF 文字层为空，此时依赖渲染图视觉通道兜底。
    另按坐标抠取右下角标题栏（图框）区域文字——含项目名称/专业/图名/图号/版本，
    是图幅身份的最可靠依据（2026-09-15 王涛建议）。
    """
    import fitz
    path = Path(file_path)
    shown_name = display_name or path.name
    cfg = _ai_cfg()

    doc = fitz.open(file_path)
    page_texts = []
    title_block = ""
    for i, page in enumerate(doc):
        if i >= cfg["max_pages"]:
            break
        try:
            page_texts.append(page.get_text("text").strip())
        except Exception:
            page_texts.append("")
        # 图框：首页右下角区域（横向 A 幅图框标题栏固定在右下）
        if i == 0 and not title_block:
            try:
                r = page.rect
                tb = page.get_text(
                    "text",
                    clip=fitz.Rect(r.width * 0.55, r.height * 0.5, r.width, r.height),
                ).strip()
                title_block = tb[:600]
            except Exception:
                pass
    total_pages = len(doc)
    doc.close()

    full = "\n".join(t for t in page_texts if t)
    ocr_text = ""
    ocr_stats = {}
    dense = False
    # 无文字层（扫描件/文字转曲）→ RapidOCR 本地补文字层（视觉+OCR 双通道互验）
    if len(full.strip()) < 100:
        try:
            doc = fitz.open(file_path)
            all_rows, page_h = [], 0
            for i, page in enumerate(doc):
                if i >= cfg["max_pages"]:
                    break
                rows, page_h = _ocr_page_image(page, dpi=cfg["ocr_dpi"])
                all_rows.extend(rows)
            doc.close()
            if all_rows:
                # 按阅读顺序排序（先上后下、同段先左后右）
                all_rows.sort(key=lambda r: (round(r[3] / 20), r[2]))
                ocr_text = "\n".join(r[0] for r in all_rows)[:cfg["ocr_text_max"]]
                heights = sorted(r[1] for r in all_rows)
                median_h = heights[len(heights) // 2]
                ocr_stats = {"boxes": len(all_rows), "median_h_px": round(median_h, 1)}
                # 密集小字判定：框多且框矮 → 触发分块渲染
                dense = len(all_rows) >= DENSE_BOX_COUNT and median_h <= DENSE_MEDIAN_H_PX
        except Exception:
            import traceback
            traceback.print_exc()  # OCR 失败留痕，不影响主流程

    lines = [f"# PDF图纸分析: {shown_name}", ""]
    lines.append(f"页数: {total_pages}" + (f"（取前 {cfg['max_pages']} 页分析）" if total_pages > cfg["max_pages"] else ""))
    if title_block:
        lines.append("")
        lines.append("## 图框信息（右下角标题栏区域：项目名称/专业/图名/图号/版本等）")
        lines.append(title_block)
    if full.strip():
        lines.append("")
        lines.append("## 图纸文字层内容（矢量文字提取）")
        lines.append(full[:cfg["text_max"]])
    elif ocr_text:
        lines.append("")
        lines.append(f"## OCR文字层（本地RapidOCR识别，共{ocr_stats.get('boxes', 0)}个文本框；"
                     "识别结果可能有误，请与渲染图像互相印证）")
        lines.append(ocr_text)
    else:
        lines.append("")
        lines.append("## 图纸无文字层（扫描件），内容以渲染图像为准")
    return {
        "filename": shown_name,
        "doc_type": "pdf",
        "page_count": total_pages,
        "title_block": title_block,
        "ocr_text": ocr_text,
        "ocr_stats": ocr_stats,
        "dense": dense,
        "description": "\n".join(lines),
    }


def render_pdf_pngs(file_path: str, out_dir: str, file_id: str,
                    dpi: int = PDF_RENDER_DPI, max_pages: int = PDF_MAX_PAGES) -> list[str]:
    """PDF 图纸逐页渲染为 PNG（矢量栅格化，保留全部图形与标注）。
    返回 PNG 路径列表（按页序），失败返回空列表不阻断上传。"""
    import fitz
    try:
        doc = fitz.open(file_path)
        outs = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            out = str(Path(out_dir) / f"{file_id}_p{i + 1}.png")
            page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72)).save(out)
            outs.append(out)
        doc.close()
        return outs
    except Exception:
        import traceback
        traceback.print_exc()
        return []


# ==================== 分块渲染（密集小字图纸专用，整页总览+网格重叠分块） ====================

TILE_OVERLAP = 0.15      # 相邻块重叠 15%：防切块边界切断文字/图元导致跨块信息错位
TILE_MAX = 6             # 单页最多分块数（控制单次请求图片数）


def tile_png(png_path: str, grid: tuple[int, int] = (2, 2)) -> list[str]:
    """把整页 PNG 裁成网格分块（相邻块 15% 重叠），返回分块路径列表。

    完整性设计（王涛要求）：① 整页总览图永远先行，作空间定位锚点；
    ② 块间 15% 重叠，边界文字/图元在相邻块中重复出现属正常拼接设计；
    ③ 块命名含行列号（_t{行}{列}），prompt 中向模型说明网格布局，
    避免裁块后跨块信息错位/拼接歧义。
    """
    from PIL import Image
    try:
        img = Image.open(png_path)
        W, H = img.size
        cols, rows = grid
        tw, th = W / cols, H / rows
        ox, oy = tw * TILE_OVERLAP, th * TILE_OVERLAP
        stem = png_path.rsplit(".", 1)[0]
        outs = []
        for r in range(rows):
            for c in range(cols):
                box = (max(0, int(c * tw - ox)), max(0, int(r * th - oy)),
                       min(W, int((c + 1) * tw + ox)), min(H, int((r + 1) * th + oy)))
                out = f"{stem}_t{r + 1}{c + 1}.png"
                img.crop(box).save(out)
                outs.append(out)
                if len(outs) >= TILE_MAX:
                    return outs
        return outs
    except Exception:
        import traceback
        traceback.print_exc()
        return []
