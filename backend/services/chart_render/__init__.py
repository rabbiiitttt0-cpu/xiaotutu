"""图表渲染调度层：spec 归一化 → 按图型路由引擎 → PNG

引擎静态路由（无外部依赖：PIL+matplotlib 为主引擎，不引入 Mermaid）：
- PIL：flowchart / mindmap / orgchart / fishbone
- matplotlib：pie / bar / line / pareto
任何渲染失败都不向上抛——返回 False，调用方把 chart item 降级为文字列表。
"""
from pathlib import Path

from config import load_config

from .chart_spec import normalize_chart_spec
from .fonts import FONT_AVAILABLE

_PIL_TYPES = {"flowchart", "mindmap", "orgchart", "fishbone"}
_MPL_TYPES = {"pie", "bar", "line", "pareto"}


def render_chart(spec: dict, out_path: Path) -> str:
    """渲染单张图。返回引擎名（pil/matplotlib），失败返回 'none'。"""
    if not FONT_AVAILABLE:
        return "none"
    try:
        if spec["type"] in _PIL_TYPES:
            from .selfdraw_diagrams import render_diagram
            render_diagram(spec, out_path)
            return "pil"
        if spec["type"] in _MPL_TYPES:
            from .selfdraw_data import render_data_chart
            render_data_chart(spec, out_path)
            return "matplotlib"
    except Exception:
        return "none"
    return "none"


def charts_in_result(result: dict) -> list[tuple[dict, dict]]:
    """遍历 sections，产出 [(item, raw_chart_spec)]（按全文出现序）"""
    found = []
    for section in result.get("sections", []):
        for item in section.get("items", []):
            if isinstance(item, dict) and "chart" in item:
                found.append((item, item["chart"]))
    return found


async def render_charts_for_record(record_id: str, result: dict, out_dir: Path) -> None:
    """/start 渲染 pass：遍历 chart items → 归一化 → 渲染 → 回填 image/engine。
    超限/失败的 chart item 降级为文字列表（category 形态），保证文档完整。"""
    cfg = load_config()
    if not getattr(cfg, "chart_enabled", True):
        return
    max_per_doc = max(int(getattr(cfg, "chart_max_per_doc", 3)), 1)

    rendered = 0
    for item, raw in charts_in_result(result):
        spec = normalize_chart_spec(raw)
        if spec and rendered < max_per_doc:
            img_name = f"{record_id}_img{rendered}.png"
            engine = render_chart(spec, out_dir / img_name)
            if engine != "none":
                item["chart"] = {**spec, "image": img_name, "engine": engine}
                rendered += 1
                continue
        # 降级：chart item → 文字列表（保留信息不丢内容）
        fallback = _chart_to_text(raw)
        item.pop("chart", None)
        if fallback:
            item.update(fallback)
        else:
            # 连文字兜底都拼不出 → 至少保留图题说明
            item["category"] = str(raw.get("title", "")) or "（图示内容渲染失败）"
            item["items"] = []


def _chart_to_text(raw: dict) -> dict | None:
    """chart spec → 文字 category 形态（渲染失败/超限兜底）"""
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title", "")) or "图示内容"
    data = raw.get("data") or {}
    lines: list[str] = []
    if data.get("nodes"):
        labels = [str(n.get("label", "")) for n in data["nodes"] if isinstance(n, dict)]
        edges = data.get("edges") or []
        edge_map = {}
        for e in edges:
            if isinstance(e, dict):
                edge_map.setdefault(e.get("from"), []).append(e.get("to"))
        id2label = {str(n.get("id")): str(n.get("label", "")) for n in data["nodes"] if isinstance(n, dict)}
        for nid, label in id2label.items():
            nexts = "、".join(id2label.get(t, t) for t in edge_map.get(nid, []))
            lines.append(f"{label}" + (f" → {nexts}" if nexts else ""))
    elif data.get("categories"):
        for c in data["categories"]:
            if isinstance(c, dict):
                lines.append(f"{c.get('name','')}：{'、'.join(str(x) for x in c.get('causes', []))}")
    elif data.get("labels"):
        vals = (data.get("series") or [{}])[0].get("values", [])
        lines = [f"{l}：{v}" for l, v in zip(data["labels"], vals)]
    if not lines:
        return None
    return {"category": title, "items": lines[:12]}
