"""Orchestrator（编排器，纯代码）：串联 LocateAgent → Snip 工具 → 生料包。

问答链路（api/drawing.py）调用 prepare()；返回 None = 回退既有路由链路。
本模块不做 LLM 调用决策以外的任何推理，一切定位细节在 locate.py / snip_locate.py。
"""
import logging

from services import snip_locate
from services.agents import locate as locate_mod  # 包内引用走绝对路径，防 __init__ 环依赖

logger = logging.getLogger("app")


def history_brief(history: list, max_chars: int = 800) -> str:
    """最近 2 轮问答纯文本（脱敏态），供 LocateAgent 解析"这个/该位置"指代"""
    msgs = [h for h in (history or []) if h.get("content")][-4:]
    lines = []
    for h in msgs:
        role = "问" if h.get("role") == "user" else "答"
        lines.append(f"{role}：{str(h['content'])[:300]}")
    return "\n".join(lines)[-max_chars:]


def card_from_info(file_id: str, info: dict, fallback_summary: str = "") -> dict:
    """ctx → LocateAgent 目录卡（画像摘要 + 图幅标题清单）"""
    frames = []
    for i, f in enumerate(info.get("frames") or [], 1):
        frames.append({"frame": f"p{i}", "title": f.get("title") or "",
                       "summary": f.get("summary") or ""})
    return {
        "file_id": file_id,
        "filename": info.get("filename", ""),
        "summary": info.get("summary") or fallback_summary or "",
        "image_count": info.get("image_count", 0),
        "frames": frames,
    }


def _ensure_axis_target(sel: dict, question: str, cards: list[dict]):
    """确定性兜底：问题提到轴号但 LocateAgent 没给 axis 型 target 时强制注入。
    （实测 deepseek-flash 偶发把轴号定位做成 keyword 聚簇，裁到错误区域）"""
    spec = snip_locate.parse_location_spec(question)
    if not spec["axes"]:
        return
    sels = sel.get("selections") or []
    has_axis = any(t.get("type") == "axis"
                   for s in sels for f in s.get("frames", [])
                   for t in f.get("targets", []))
    if has_axis or not sels:
        return
    n_crops = sum(1 for s in sels for f in s.get("frames", [])
                  for t in f.get("targets", []) if t.get("type") != "frame")
    if n_crops >= locate_mod.MAX_CROPS_TOTAL:
        return
    s0 = sels[0]
    card = next((c for c in cards if c["file_id"] == s0.get("file_id")), {})
    idx = 1 if (card.get("image_count") or 1) > 1 else 0
    target = {"type": "axis", "axes": [a["raw"] for a in spec["axes"]][:2],
              "purpose": "轴号交点定位"}
    if s0.get("frames"):
        s0["frames"][0].setdefault("targets", []).append(target)
    else:
        s0["frames"] = [{"frame": f"p{idx}", "frame_index": idx,
                         "frame_title": "", "targets": [target]}]


async def prepare(*, question: str, history: list, cards: list[dict],
                  info_by_fid: dict, llm_service, provider_index: int,
                  relations_desc: str = "") -> dict | None:
    """Locate → Snip 生料包。返回：
    {selected_file_ids, reason, images:[{b64,note}], texts:[str], notes:str}
    任一步失败/无有效定位 → None（调用方回退既有链路）。"""
    sel = await locate_mod.locate(
        llm_service, provider_index, question=question,
        history_brief=history_brief(history), cards=cards,
        relations_desc=relations_desc)
    if not sel:
        logger.warning("[orchestrator] LocateAgent 无有效定位，回退既有链路")
        return None
    _ensure_axis_target(sel, question, cards)
    try:
        payload = snip_locate.build_payload(sel["selections"], info_by_fid, question)
    except Exception:
        logger.exception("[orchestrator] build_payload 失败")
        return None
    logger.info("[orchestrator] 定位完成：%s｜图=%d 裁剪=%d 理由=%s",
                [s["file_id"] for s in sel["selections"]],
                len(sel["selections"]), len(payload["images"]),
                sel.get("reason", "")[:80])
    selected_ids = []
    for s in sel["selections"]:
        if s["file_id"] not in selected_ids:
            selected_ids.append(s["file_id"])
    notes = ""
    if payload["images"]:
        notes = "\n\n附图说明：\n" + "\n".join(
            f"第{i + 1}张：{img['note']}" for i, img in enumerate(payload["images"]))
        if len(payload["images"]) > 1:
            notes += "\n含多张图时请对照比较后回答。"
    return {
        "selected_file_ids": selected_ids,
        "reason": sel.get("reason", ""),
        "images": payload["images"],
        "texts": payload["texts"],
        "notes": notes,
    }
