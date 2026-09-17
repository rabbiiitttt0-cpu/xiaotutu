"""chart spec 归一化与校验（LLM 输出容错层）

LLM 输出的 chart spec 字段可能不规范：类型别名、中英文混用、数据长度不齐等。
统一在这里清洗，结构性缺失返回 None（调用方降级为文字列表）。
"""
import re

CHART_TYPES = {"flowchart", "mindmap", "orgchart", "fishbone",
               "pie", "bar", "line", "pareto"}

# 同族转换组（换图型时同族互转，不调 LLM）
CHART_FAMILIES = {
    "graph": {"flowchart", "mindmap", "orgchart"},
    "data": {"pie", "bar", "pareto"},
    "fishbone": {"fishbone"},
    "line": {"line"},
}

_TYPE_ALIASES = {
    "flow": "flowchart", "流程图": "flowchart", "流程": "flowchart",
    "mind": "mindmap", "思维导图": "mindmap", "脑图": "mindmap",
    "org": "orgchart", "org_chart": "orgchart", "organization": "orgchart",
    "组织架构图": "orgchart", "组织结构图": "orgchart", "架构图": "orgchart",
    "fish": "fishbone", "鱼骨图": "fishbone", "因果图": "fishbone", "石川图": "fishbone",
    "饼图": "pie", "饼状图": "pie", "扇形图": "pie",
    "histogram": "bar", "柱状图": "bar", "直方图": "bar", "条形图": "bar", "柱图": "bar",
    "折线图": "line", "趋势图": "line", "曲线图": "line",
    "帕累托图": "pareto", "柏拉图": "pareto", "排列图": "pareto",
}

MAX_NODES = 30


def _norm_type(raw: str) -> str:
    t = (raw or "").strip().lower().replace(" ", "").replace("_chart", "").replace("chart", "")
    t = t or (raw or "").strip().lower()
    if t in CHART_TYPES:
        return t
    for k, v in _TYPE_ALIASES.items():
        if k in t or k == t:
            return v
    # 原文直查（中文别名可能已被 lower 变形）
    raw_clean = (raw or "").strip()
    if raw_clean in _TYPE_ALIASES:
        return _TYPE_ALIASES[raw_clean]
    return ""


def _to_float_list(values) -> list[float]:
    out = []
    for v in values or []:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            m = re.search(r"-?\d+\.?\d*", str(v))
            out.append(float(m.group()) if m else 0.0)
    return out


def normalize_chart_spec(raw: dict) -> dict | None:
    """校验并补全 chart spec。结构性缺失返回 None。"""
    if not isinstance(raw, dict):
        return None
    ctype = _norm_type(str(raw.get("type", "")))
    if ctype not in CHART_TYPES:
        return None

    data = raw.get("data") or {}
    title = str(raw.get("title", ""))[:60]

    if ctype in ("flowchart", "mindmap", "orgchart"):
        nodes = data.get("nodes") or []
        edges = data.get("edges") or []
        clean_nodes = []
        for n in nodes[:MAX_NODES]:
            if isinstance(n, dict) and n.get("id") and n.get("label"):
                shape = n.get("shape", "rect")
                clean_nodes.append({
                    "id": str(n["id"]), "label": str(n["label"])[:40],
                    "shape": shape if shape in ("rect", "diamond", "round") else "rect",
                })
        node_ids = {n["id"] for n in clean_nodes}
        clean_edges = []
        for e in edges:
            if isinstance(e, dict) and e.get("from") in node_ids and e.get("to") in node_ids:
                clean_edges.append({"from": str(e["from"]), "to": str(e["to"]),
                                    "label": str(e.get("label", ""))[:20]})
        if len(clean_nodes) < 2 or not clean_edges:
            return None
        data = {"nodes": clean_nodes, "edges": clean_edges}
        if ctype in ("mindmap", "orgchart"):
            root = str(data.get("root") or "")
            data["root"] = root if root in node_ids else clean_nodes[0]["id"]

    elif ctype == "fishbone":
        effect = str(data.get("effect", "")).strip()
        cats = []
        for c in (data.get("categories") or [])[:6]:
            if isinstance(c, dict) and c.get("name"):
                causes = [str(x)[:40] for x in (c.get("causes") or [])][:6]
                if causes:
                    cats.append({"name": str(c["name"])[:12], "causes": causes})
        if not effect or not cats:
            return None
        data = {"effect": effect[:40], "categories": cats}

    else:  # pie/bar/line/pareto
        labels = [str(x)[:20] for x in (data.get("labels") or [])]
        series = []
        for s in (data.get("series") or [])[:3]:
            if isinstance(s, dict):
                series.append({"name": str(s.get("name", ""))[:20],
                               "values": _to_float_list(s.get("values"))})
        if not labels or not series or not series[0]["values"]:
            return None
        # 长度对齐（截短到最短）
        n = min(len(labels), min(len(s["values"]) for s in series))
        if n < 2:
            return None
        labels = labels[:n]
        series = [{"name": s["name"], "values": s["values"][:n]} for s in series]
        data = {"labels": labels, "series": series}

    return {"type": ctype, "title": title, "data": data}


def same_family(a: str, b: str) -> bool:
    """两图型是否同族（可本地互转）"""
    for fam in CHART_FAMILIES.values():
        if a in fam and b in fam:
            return True
    return False
