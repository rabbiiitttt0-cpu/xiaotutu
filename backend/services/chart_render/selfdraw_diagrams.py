"""PIL 自绘图形类图表：flowchart / orgchart / mindmap / fishbone

统一视觉约定：白底、圆角矩形节点、主色 #409EFF 边框 / #ECF5FF 填充（与前端主色一致）。
所有布局解析计算，不依赖外部布局库；CJK 文本按字折行。
"""
from pathlib import Path

from PIL import Image, ImageDraw

from .fonts import pil_font

# 视觉常量
BORDER = "#409EFF"
FILL = "#ECF5FF"
ROOT_FILL = "#409EFF"
ROOT_TEXT = "#FFFFFF"
TEXT = "#303133"
GRAY = "#909399"
WARN = "#E6A23C"
MARGIN = 40
NODE_PAD_X = 18
NODE_PAD_Y = 10
LEVEL_GAP = 70
SIBLING_GAP = 30
FONT_SIZE = 20
TITLE_SIZE = 28


def _wrap_cjk(text: str, font, max_width: int, draw) -> list[str]:
    """CJK 按字、英文按词折行"""
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if draw.textlength(trial, font=font) > max_width and cur:
            lines.append(cur)
            cur = ch if ch.strip() else ""
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines or [""]


def _node_size(label: str, font, draw, max_w=280) -> tuple[int, int, list[str]]:
    lines = _wrap_cjk(label, font, max_w - 2 * NODE_PAD_X, draw)
    w = int(max(draw.textlength(l, font=font) for l in lines)) + 2 * NODE_PAD_X
    h = len(lines) * (FONT_SIZE + 8) + 2 * NODE_PAD_Y
    return w, h, lines


def _draw_node(draw, x, y, w, h, label_lines, shape="rect", root=False):
    fill = ROOT_FILL if root else FILL
    outline = BORDER
    text_color = ROOT_TEXT if root else TEXT
    if shape == "diamond":
        pts = [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]
        draw.polygon(pts, fill=fill, outline=outline, width=2)
    elif shape == "round":
        draw.rounded_rectangle([x, y, x + w, y + h], radius=h / 2, fill=fill, outline=outline, width=2)
    else:
        draw.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=fill, outline=outline, width=2)
    font = pil_font(FONT_SIZE)
    total_h = len(label_lines) * (FONT_SIZE + 8)
    ty = y + (h - total_h) / 2
    for line in label_lines:
        tw = draw.textlength(line, font=font)
        draw.text((x + (w - tw) / 2, ty), line, font=font, fill=text_color)
        ty += FONT_SIZE + 8


def _draw_arrow(draw, x1, y1, x2, y2, label="", font=None, elbow=False):
    """父底中点→子顶中点箭头；elbow=True 画肘形折线（组织架构图）"""
    if elbow:
        mid_y = (y1 + y2) / 2
        draw.line([(x1, y1), (x1, mid_y), (x2, mid_y), (x2, y2)], fill=BORDER, width=2)
    else:
        draw.line([(x1, y1), (x2, y2)], fill=BORDER, width=2)
    # 末端箭头
    import math
    ang = math.atan2(y2 - y1, x2 - x1)
    size = 10
    p1 = (x2 - size * math.cos(ang - 0.5), y2 - size * math.sin(ang - 0.5))
    p2 = (x2 - size * math.cos(ang + 0.5), y2 - size * math.sin(ang + 0.5))
    draw.polygon([(x2, y2), p1, p2], fill=BORDER)
    if label and font:
        lx, ly = (x1 + x2) / 2, (y1 + y2) / 2
        draw.text((lx + 4, ly - FONT_SIZE - 4), label, font=font, fill=GRAY)


def _layer_layout(nodes, edges, nodes_index):
    """longest-path 分层 + 层内父重心排序。
    回边（会形成环的边）不参与分层只参与绘制——否则循环会把前序节点压到下游层。"""
    # 可达性（memo DFS），用于回边检测
    children_all: dict[str, list[str]] = {}
    for e in edges:
        children_all.setdefault(e["from"], []).append(e["to"])

    # 经典 DFS 回边检测：只排除「指向 DFS 栈上祖先」的边（反馈弧），不误伤环中其他边
    back: set[tuple[str, str]] = set()
    visited: set[str] = set()
    on_stack: set[str] = set()

    def dfs(u: str):
        on_stack.add(u)
        for v in children_all.get(u, []):
            if v in on_stack:
                back.add((u, v))
            elif v not in visited:
                visited.add(v)
                dfs(v)
        on_stack.discard(u)

    for n in nodes:
        if n["id"] not in visited:
            visited.add(n["id"])
            dfs(n["id"])

    layering_edges = [e for e in edges if (e["from"], e["to"]) not in back]

    preds = {n["id"]: [] for n in nodes}
    for e in layering_edges:
        preds[e["to"]].append(e["from"])
    layer = {}
    visiting = set()

    def depth(nid):
        if nid in layer:
            return layer[nid]
        if nid in visiting:
            return 0
        visiting.add(nid)
        d = 0
        for p in preds[nid]:
            d = max(d, depth(p) + 1)
        visiting.discard(nid)
        layer[nid] = d
        return d

    for n in nodes:
        depth(n["id"])
    # 层内按父节点平均位置排序（barycenter 去交叉）
    by_layer: dict[int, list[str]] = {}
    for nid, lv in layer.items():
        by_layer.setdefault(lv, []).append(nid)
    order = {}
    for lv in sorted(by_layer):
        ids = by_layer[lv]
        if lv == 0:
            ids.sort(key=lambda i: nodes_index[i])
        else:
            def bary(i):
                ps = [order.get(p, (0, 0))[1] for p in preds[i] if p in order]
                return sum(ps) / len(ps) if ps else 0
            ids.sort(key=bary)
        for idx, nid in enumerate(ids):
            order[nid] = (lv, idx)
    return order, by_layer


def _render_layered(data: dict, out_path: Path, elbow=False):
    """flowchart / orgchart 分层渲染"""
    nodes, edges = data["nodes"], data["edges"]
    nodes_index = {n["id"]: i for i, n in enumerate(nodes)}
    font = pil_font(FONT_SIZE)

    probe = Image.new("RGB", (10, 10), "white")
    d0 = ImageDraw.Draw(probe)
    sizes = {}
    for n in nodes:
        sizes[n["id"]] = _node_size(n["label"], font, d0)

    order, by_layer = _layer_layout(nodes, edges, nodes_index)
    max_layer = max(by_layer)
    # 每层 x 均布（按层内最大宽度）
    layer_widths = {}
    for lv, ids in by_layer.items():
        w = sum(sizes[i][0] for i in ids) + SIBLING_GAP * (len(ids) - 1)
        layer_widths[lv] = w
    canvas_w = max(layer_widths.values()) + 2 * MARGIN
    # 画布宽度不得小于标题宽度（防长标题被裁切）
    title = data.get("_title", "")
    if title:
        title_font0 = pil_font(TITLE_SIZE)
        canvas_w = max(canvas_w, d0.textlength(title, font=title_font0) + 2 * MARGIN)
    layer_h = {}
    for lv, ids in by_layer.items():
        layer_h[lv] = max(sizes[i][1] for i in ids)
    canvas_h = sum(layer_h.values()) + LEVEL_GAP * max_layer + 2 * MARGIN + TITLE_SIZE + 40

    img = Image.new("RGB", (int(canvas_w), int(canvas_h)), "white")
    draw = ImageDraw.Draw(img)

    # 标题
    title_font = pil_font(TITLE_SIZE)
    title = data.get("_title", "")
    if title:
        tw = draw.textlength(title, font=title_font)
        draw.text(((canvas_w - tw) / 2, MARGIN / 2), title, font=title_font, fill=TEXT)

    # 计算坐标
    pos = {}
    y = MARGIN + TITLE_SIZE + 20
    for lv in sorted(by_layer):
        ids = by_layer[lv]
        x = (canvas_w - layer_widths[lv]) / 2
        for nid in ids:
            w, h = sizes[nid][0], sizes[nid][1]
            pos[nid] = (x, y, w, h)
            x += w + SIBLING_GAP
        y += layer_h[lv] + LEVEL_GAP

    # 先画边
    for e in edges:
        if e["from"] in pos and e["to"] in pos:
            x1, y1, w1, h1 = pos[e["from"]]
            x2, y2, w2, h2 = pos[e["to"]]
            _draw_arrow(draw, x1 + w1 / 2, y1 + h1, x2 + w2 / 2, y2,
                        e.get("label", ""), font, elbow=elbow)
    # 后画节点
    for n in nodes:
        x, y, w, h = pos[n["id"]]
        _draw_node(draw, x, y, w, h, sizes[n["id"]][2],
                   shape=n.get("shape", "rect"), root=False)

    img.save(out_path)


def _render_mindmap(data: dict, out_path: Path):
    """水平树：root 左侧居中，子树高度递归分配（环安全：visited 防死循环）"""
    nodes = {n["id"]: n for n in data["nodes"]}
    edges = data["edges"]
    root = data.get("root") or data["nodes"][0]["id"]
    children: dict[str, list[str]] = {}
    for e in edges:
        children.setdefault(e["from"], []).append(e["to"])

    font = pil_font(FONT_SIZE)
    probe = Image.new("RGB", (10, 10), "white")
    d0 = ImageDraw.Draw(probe)
    sizes = {nid: _node_size(n["label"], font, d0, max_w=240) for nid, n in nodes.items()}

    LEAF_H = 56

    def subtree_height(nid, seen=frozenset()):
        kids = [k for k in children.get(nid, []) if k not in seen]
        if not kids:
            return max(LEAF_H, sizes[nid][1])
        seen2 = seen | {nid}
        return sum(subtree_height(k, seen2) for k in kids) + 14 * (len(kids) - 1)

    # 递归布局
    pos = {}
    X_GAP = 220

    def layout(nid, x, y_top, seen=frozenset()):
        h_total = subtree_height(nid, seen)
        w, h = sizes[nid][0], sizes[nid][1]
        y = y_top + (h_total - h) / 2
        pos[nid] = (x, y, w, h)
        seen2 = seen | {nid}
        cy = y_top
        for k in children.get(nid, []):
            if k in seen2:
                continue
            layout(k, x + X_GAP, cy, seen2)
            cy += subtree_height(k, seen2) + 14
        return h_total

    total_h = layout(root, MARGIN, MARGIN + TITLE_SIZE + 20)
    max_x = max(x + w for x, y, w, h in pos.values()) if pos else 400
    img = Image.new("RGB", (int(max_x + MARGIN), int(total_h + MARGIN * 2 + TITLE_SIZE)), "white")
    draw = ImageDraw.Draw(img)

    title = data.get("_title", "")
    if title:
        title_font = pil_font(TITLE_SIZE)
        tw = draw.textlength(title, font=title_font)
        draw.text(((img.width - tw) / 2, MARGIN / 2), title, font=title_font, fill=TEXT)

    # 先画边（折线）
    for e in edges:
        if e["from"] in pos and e["to"] in pos:
            x1, y1, w1, h1 = pos[e["from"]]
            x2, y2, w2, h2 = pos[e["to"]]
            mid_x = (x1 + w1 + x2) / 2
            draw.line([(x1 + w1, y1 + h1 / 2), (mid_x, y1 + h1 / 2),
                       (mid_x, y2 + h2 / 2), (x2, y2 + h2 / 2)], fill=BORDER, width=2)
    for nid, (x, y, w, h) in pos.items():
        _draw_node(draw, x, y, w, h, sizes[nid][2],
                   shape="round", root=(nid == root))

    img.save(out_path)


def _render_fishbone(data: dict, out_path: Path):
    """鱼骨图：脊柱+鱼头+上下交替 45° 斜骨"""
    effect = data["effect"]
    cats = data["categories"]
    font = pil_font(FONT_SIZE)
    cat_font = pil_font(FONT_SIZE + 2)

    n = len(cats)
    spine_len = max(900, n * 300)
    W = spine_len + 420
    H = max(560, n * 150)
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)

    title = data.get("_title", "")
    if title:
        title_font = pil_font(TITLE_SIZE)
        tw = draw.textlength(title, font=title_font)
        draw.text(((W - tw) / 2, 16), title, font=title_font, fill=TEXT)

    spine_y = H // 2
    x0, x1 = MARGIN + 60, MARGIN + 60 + spine_len
    # 鱼头（三角）+ effect
    draw.polygon([(x1, spine_y - 26), (x1 + 70, spine_y), (x1, spine_y + 26)],
                 fill=WARN, outline="#B88230")
    eff_lines = _wrap_cjk(effect, cat_font, 240, draw)
    ey = spine_y - len(eff_lines) * 16
    for l in eff_lines:
        draw.text((x1 + 84, ey), l, font=cat_font, fill=TEXT)
        ey += FONT_SIZE + 12
    # 脊柱
    draw.line([(x0, spine_y), (x1, spine_y)], fill=TEXT, width=4)

    # 斜骨
    for i, cat in enumerate(cats):
        bx = x0 + (i + 0.5) * (spine_len / n)
        up = (i % 2 == 0)
        bone_len = 190
        dx = int(bone_len * 0.7071)
        dy = -int(bone_len * 0.7071) if up else int(bone_len * 0.7071)
        ex, ey = bx + dx, spine_y + dy
        draw.line([(bx, spine_y), (ex, ey)], fill=BORDER, width=3)
        # 类别名（骨外端加粗）
        cw = draw.textlength(cat["name"], font=cat_font)
        draw.text((ex - cw / 2, ey - (34 if up else -10)), cat["name"], font=cat_font, fill=BORDER)
        # causes 沿骨均布
        causes = cat["causes"]
        for j, cause in enumerate(causes):
            t = (j + 1) / (len(causes) + 1)
            cx, cy = bx + dx * t, spine_y + dy * t
            # 短支（水平）
            stub = 90
            sx = cx + stub
            draw.line([(cx, cy), (sx, cy)], fill=GRAY, width=2)
            cl = _wrap_cjk(cause, font, 220, draw)
            ly = cy - (len(cl) * 26 + 4) if up else cy + 4
            for l in cl:
                draw.text((cx + 6, ly), l, font=font, fill=TEXT)
                ly += 26

    img.save(out_path)


def render_diagram(spec: dict, out_path: Path):
    """图形类统一入口"""
    data = dict(spec["data"])
    data["_title"] = spec.get("title", "")
    ctype = spec["type"]
    if ctype == "flowchart":
        _render_layered(data, out_path, elbow=False)
    elif ctype == "orgchart":
        _render_layered(data, out_path, elbow=True)
    elif ctype == "mindmap":
        _render_mindmap(data, out_path)
    elif ctype == "fishbone":
        _render_fishbone(data, out_path)
    else:
        raise ValueError(f"非图形类图型: {ctype}")
