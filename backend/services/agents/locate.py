"""LocateAgent（窗口A）：三级定位 —— 图纸 → 图幅 → 部位。

输入：问题 + 最近历史 + 目录卡（文件名/画像摘要/图幅标题/批次关系描述）
输出：selections JSON，交给 snip_locate.build_payload 变成"生料包"。
本 Agent 纯文本、不做任何图像操作；输出校验不合格返回 None（回退既有路由）。

target 类型：
  axis    —— 轴号交点部位裁剪（axes: ["B-8","B-A"]）
  table   —— 关键词密度聚簇的表格/详图区裁剪（keywords: ["DJj","配筋"]）
  region  —— 方位区域裁剪（region: "右上" 等）
  keyword —— 关键词命中点裁剪
  frame   —— 整图幅级（对比型问题）：注入图幅切片 + 按图幅分组的文字摘要
"""
from .base import run_agent

MODULE = "drawing_locate"

# 限额（超出截断，防单题图片/区域爆炸）
MAX_FILES = 4
MAX_FRAMES_PER_FILE = 3
MAX_TARGETS_PER_FRAME = 2
MAX_CROPS_TOTAL = 3  # 部位级裁剪总数（frame 型注入整幅不占此额度）

_SYS = """你是工程图纸定位专家。任务：根据用户问题，从给定图纸目录中定位回答所需的内容位置。

定位分三级：
1. 图纸定位：结合文件名、图纸摘要、批次关系描述，判断问题涉及哪几张图纸
2. 图幅定位：每张图纸可能含多个图幅（p1/p2/…，各有图名），判断涉及哪几个图幅
3. 部位定位：图幅内的具体部位——轴号交点、表格/详图区、方位区域；对比类问题（如
  "一层到二层哪些柱子截面变了"）选两个图幅各给一个 frame 型 target 即可

只输出JSON：
{"selections":[{"file_id":"图纸id",
  "frames":[{"frame":"p1","frame_title":"图名",
    "targets":[
      {"type":"axis","axes":["B-8","B-A"],"purpose":"查什么"},
      {"type":"table","keywords":["关键词"],"purpose":"查什么"},
      {"type":"region","region":"右上","purpose":"查什么"},
      {"type":"keyword","keywords":["关键词"],"purpose":"查什么"},
      {"type":"frame","purpose":"整幅对比/综览"}
    ]}]}],
 "reason":"一句话定位理由"}

规则：
- **问题中出现轴号（如 B-8、B-A、8轴、A轴）→ 必须产出 type=axis 的 target，axes 填问题中的轴号原文（如 ["B-8","B-A"]），禁止用 keyword/table 代替轴号定位**
- 问题不含位置/对象线索且只是泛泛询问时，仍可选图选幅，targets 留空数组
- "这个/该位置"等指代从对话历史中解析
- 拿不准就少选，最多 4 张图纸、每图最多 3 个图幅、每图幅最多 2 个部位
- 只输出JSON"""


def _catalog_text(cards: list[dict], relations_desc: str = "") -> str:
    """目录卡文本：文件名 + 画像摘要 + 图幅标题清单（脱敏态， locating 足够）"""
    lines = []
    for c in cards:
        line = f"图纸 [{c['file_id']}] {c.get('filename', '')}"
        if c.get("summary"):
            line += f"\n  摘要：{c['summary'][:300]}"
        frames = c.get("frames") or []
        if frames:
            fl = "；".join(
                f"{f.get('frame', f'p{i + 1}')}:{(f.get('title') or f.get('summary') or '')[:40]}"
                for i, f in enumerate(frames[:40]))
            line += f"\n  图幅：{fl}"
        elif c.get("image_count", 0) > 1:
            line += f"\n  图幅：共{c['image_count'] - 1}个切片（标题未知）"
        lines.append(line)
    text = "\n".join(lines)
    if relations_desc:
        text = f"【本批图纸关系描述】\n{relations_desc[:1200]}\n\n【图纸目录】\n{text}"
    return text


def _validate(parsed, cards) -> dict | None:
    """结构校验 + 限额截断。file_id/frame 必须在目录内，否则整条丢弃。"""
    if not isinstance(parsed, dict):
        return None
    sels = parsed.get("selections")
    if not isinstance(sels, list):
        return None
    by_id = {c["file_id"]: c for c in cards}
    out = []
    crops = 0
    for s in sels[:MAX_FILES]:
        if not isinstance(s, dict):
            continue
        card = by_id.get(s.get("file_id"))
        if not card:
            continue
        n_frames = max(0, (card.get("image_count") or 1) - 1)  # 切片数（首页=总览）
        frames = []
        for f in (s.get("frames") or [])[:MAX_FRAMES_PER_FILE]:
            if not isinstance(f, dict):
                continue
            fname = str(f.get("frame") or "")
            # frame 形如 p1/p2…；无切片图纸只允许 p0（整图）
            try:
                idx = int(fname.lstrip("pP"))
            except ValueError:
                continue
            if idx < 0 or idx > n_frames:
                continue
            targets = []
            for t in (f.get("targets") or [])[:MAX_TARGETS_PER_FRAME]:
                if not isinstance(t, dict):
                    continue
                ttype = t.get("type")
                if ttype not in ("axis", "table", "region", "keyword", "frame"):
                    continue
                if ttype == "axis" and not t.get("axes"):
                    continue
                if ttype in ("table", "keyword") and not t.get("keywords"):
                    continue
                if ttype != "frame":
                    if crops >= MAX_CROPS_TOTAL:
                        continue
                    crops += 1
                targets.append(t)
            frames.append({"frame": f"p{idx}", "frame_index": idx,
                           "frame_title": str(f.get("frame_title") or ""),
                           "targets": targets})
        if frames:
            out.append({"file_id": card["file_id"], "frames": frames})
    if not out:
        return None
    return {"selections": out, "reason": str(parsed.get("reason") or "")[:200]}


async def locate(llm_service, provider_index: int, *, question: str,
                 history_brief: str, cards: list[dict],
                 relations_desc: str = "") -> dict | None:
    """三级定位主入口。失败/非法/无有效选择 → None。"""
    if not cards:
        return None
    user = f"用户问题：{question}\n"
    if history_brief:
        user += f"\n最近对话（供解析指代）：\n{history_brief[-800:]}\n"
    user += f"\n{_catalog_text(cards, relations_desc)}"
    parsed = await run_agent(llm_service, provider_index, module=MODULE,
                             system=_SYS, user=user,
                             max_tokens=1500, temperature=0.1, expect_json=True)
    if parsed is None:
        return None
    return _validate(parsed, cards)
