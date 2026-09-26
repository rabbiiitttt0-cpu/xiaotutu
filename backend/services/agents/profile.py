"""ProfileAgent（窗口C，离线）：预处理期生成图纸画像 + 批次关系图。

- summarize_drawing：单图内容摘要 + 各图幅一句话说明（写回 ctx，供 LocateAgent 目录卡）
- build_relations：一批图纸的关系图（节点/边/自然语言描述），供定位推理与前端预览

全部走脱敏态文本（ctx 本就是密文；filename 不敏感）。失败返回 None，不阻塞预处理。
"""
from .base import run_agent

MODULE = "drawing_profile"

_SUMMARY_SYS = """你是工程图纸分析专家。根据给定图纸的结构化信息（文件名/图框标题/图幅标题/标注抽样），
输出该图纸的画像JSON：
{"summary":"本图纸总体内容，2-4句话（专业/对象/包含哪些图幅内容）",
 "frame_summaries":[{"frame":"p1","title":"图幅图名","summary":"该图幅一句话内容"}]}
规则：frame_summaries 按给定图幅清单逐一给出，不知道内容的图幅 summary 留空字符串；
不要编造图幅清单之外的图幅；只输出JSON。"""

_REL_SYS = """你是工程图纸管理专家。给定同一批上传图纸的清单（文件名/目录路径/内容摘要），
推断图纸之间的关系，输出JSON：
{"nodes":[{"file_id":"图纸id","kind":"类别，如 结构/建筑/给排水/暖通/电气/目录/说明"}],
 "edges":[{"from":"file_id","to":"file_id","relation":"关系，如 详图引用/专业配套/分层对应/总-分"}],
 "description":"这批图纸的整体关系与分工，3-8句话，供后续问答定位参考"}
规则：不确定的关系不要编；同一目录/同一专业前缀是强信号；只输出JSON。"""


def _card_text(info: dict, filename: str) -> str:
    bits = [f"文件名：{filename}"]
    tb = (info.get("title_block") or "").strip()
    if tb:
        bits.append(f"图框标题栏：{tb[:200]}")
    frames = info.get("frames") or []
    if frames:
        bits.append("图幅：" + "；".join(
            f"{f.get('frame', f'p{i + 1}')}:{(f.get('title') or '')[:40]}"
            for i, f in enumerate(frames[:40])))
    elif (info.get("frame_count") or 0) > 1:
        bits.append(f"图幅：共{info['frame_count']}个（标题未知）")
    anns, seen = [], set()
    for t in info.get("text_annotations") or []:
        txt = (t.get("text") or "").strip()
        if txt and txt not in seen:
            seen.add(txt)
            anns.append(txt)
        if len(anns) >= 120:
            break
    if anns:
        bits.append("标注抽样：" + "；".join(anns)[:1200])
    return "\n".join(bits)


async def summarize_drawing(llm_service, provider_index: int, info: dict,
                            filename: str) -> dict | None:
    """单图画像 → {summary, frame_summaries:[{frame,title,summary}]}，失败 None。"""
    parsed = await run_agent(llm_service, provider_index, module=MODULE,
                             system=_SUMMARY_SYS, user=_card_text(info, filename),
                             max_tokens=1500, temperature=0.1, expect_json=True)
    if not isinstance(parsed, dict) or not parsed.get("summary"):
        return None
    fs = parsed.get("frame_summaries")
    return {
        "summary": str(parsed["summary"])[:500],
        "frame_summaries": [
            {"frame": str(f.get("frame") or ""), "title": str(f.get("title") or "")[:60],
             "summary": str(f.get("summary") or "")[:200]}
            for f in fs if isinstance(f, dict)
        ] if isinstance(fs, list) else [],
    }


async def build_relations(llm_service, provider_index: int,
                          cards: list[dict]) -> dict | None:
    """批次关系图。cards: [{file_id, filename, rel_path, summary}]，失败 None。"""
    if not cards:
        return None
    listing = "\n".join(
        f"[{c['file_id']}] {c.get('rel_path') or c.get('filename', '')}"
        + (f"｜{c['summary'][:200]}" if c.get("summary") else "")
        for c in cards)
    parsed = await run_agent(llm_service, provider_index, module=MODULE,
                             system=_REL_SYS,
                             user=f"本批图纸共 {len(cards)} 张：\n{listing}",
                             max_tokens=2048, temperature=0.1, expect_json=True)
    if not isinstance(parsed, dict):
        return None
    valid = {c["file_id"] for c in cards}
    nodes = [n for n in (parsed.get("nodes") or [])
             if isinstance(n, dict) and n.get("file_id") in valid]
    edges = [e for e in (parsed.get("edges") or [])
             if isinstance(e, dict) and e.get("from") in valid and e.get("to") in valid]
    return {
        "nodes": [{"file_id": n["file_id"], "kind": str(n.get("kind") or "")[:20]}
                  for n in nodes],
        "edges": [{"from": e["from"], "to": e["to"],
                   "relation": str(e.get("relation") or "")[:40]} for e in edges],
        "description": str(parsed.get("description") or "")[:2000],
    }
