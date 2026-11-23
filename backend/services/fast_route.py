# -*- coding: utf-8 -*-
"""一期优化#1/#2：问题分类双路线 + 快路文本直答

问题分两类：
- 快路（FAST）：答案可完全从图纸已有文本数据（文字标注/标题栏/说明/图纸总览）
  摘取或归纳 → 跳过 LocateAgent 定位与图像预处理，直接文本调用出答案
- 慢路（SLOW）：需要视觉精读（空间位置/构件统计/图形细节）→ 走既有编排流程

误分类代价不对称（视觉题误判成快路 = 给错答案），四层防护：
1. 关键词规则前置（零成本、零延迟）：明显视觉词 → 直接慢路；明显图签/文字词 → 直接快路候选
2. 其余交轻量 LLM 单次分类（temperature=0.1，只输出 FAST/SLOW，拿不准 → SLOW）
3. 快路证据不足（文本数据太薄）→ 不尝试，直接慢路（在调用方做证据门）
4. 快路回答含 [[NEED_IMAGE]] 标记（模型自判文本不足）→ 自动降级慢路

本模块只依赖 llm_service 接口，不含 drawing 层数据读取，可独立单测。
"""
import re

# 快路自降级标记：模型判断文本数据不足以回答时只输出该标记
FAST_MARKER = "[[NEED_IMAGE]]"

# 明显需要看图（空间方位/构件实体/数量统计/图形关系）→ 直接慢路，省一次分类调用
_SLOW_RULES = re.compile(
    r"东边|西边|南边|北边|以东|以西|以南|以北|左侧|右侧|左上|右上|左下|右下|最[东南西北]|"
    r"空间|位置在|哪里|哪儿|哪个位置|分布|走向|相邻|距离|对齐|重叠|遮挡|"
    r"多少(根|个|处|间|道|面|条|块|套)|数量统计|统计.{0,6}数量|数一数|共有多少|"
    r"尺寸是|多大|配筋|标高|节点|详图|剖面|大样")

# 明显可从文本摘取（图签/说明/标注文字/概况归纳类）→ 直接快路候选
_FAST_RULES = re.compile(
    r"图名|图号|标题栏|图签|项目名称|建设单位|设计单位|出图日期|会签|"
    r"什么比例|比例是|版本|版次|修订|"
    r"设计说明|说明(里|中|写|如何|讲)|文字标注|标注了|写了什么|什么文字|列出.{0,6}文字|"
    r"概括|概述|总结|讲了什么|包含哪些图|哪些图纸|多少张图|图幅.{0,4}表达")


def rules_classify(question: str) -> str:
    """规则分类：'fast' | 'slow' | ''（''=需 LLM 分类）
    两组规则同时命中（如"说明里关于东边柱子写了什么"）→ 交 LLM 裁决"""
    q = (question or "").strip()
    if not q:
        return ""
    fast = bool(_FAST_RULES.search(q))
    slow = bool(_SLOW_RULES.search(q))
    if fast and not slow:
        return "fast"
    if slow and not fast:
        return "slow"
    return ""


_CLASSIFY_SYSTEM = """你是图纸问答路由器。判断用户问题能否完全从「图纸文本数据」（文字标注、标题栏、说明文字、图纸总览）中摘取或归纳出答案，无需查看图纸图像。
- 需要识别图形、空间位置、构件数量、尺寸图形、节点构造等视觉信息 → SLOW
- 仅需读取或汇总已有文字信息（图签信息、说明文字、文字清单、概况归纳）→ FAST
- 拿不准 → SLOW（宁可多走视觉链路，也不能给错答案）
只输出一个英文单词：FAST 或 SLOW，不要输出任何其他内容。"""


_CLASSIFY_CACHE: dict = {}          # (provider_index, 问题指纹) → bool
_CLASSIFY_CACHE_MAX = 5000


def _classify_key(question: str) -> str:
    """问题指纹：去空白 + 小写。分类只依赖问题文本，与图纸内容无关 → 可永久缓存。"""
    return re.sub(r"\s+", "", (question or "")).lower()


async def llm_classify(question: str, llm_service, provider_index: int) -> bool:
    """轻量 LLM 单次分类。返回 True=快路。异常/解析失败/预算耗尽一律按慢路（False）。

    结果只依赖问题文本（与图纸无关），按 (provider_index, 问题指纹) 缓存，
    避免同一/相似问题重复跑分类调用；provider 变更自动换 key 重分类。"""
    fkey = _classify_key(question)
    if not fkey:
        return False
    ckey = (provider_index, fkey)
    if ckey in _CLASSIFY_CACHE:
        return _CLASSIFY_CACHE[ckey]
    try:
        out = await llm_service.chat_complete(
            messages=[{"role": "system", "content": _CLASSIFY_SYSTEM},
                      {"role": "user", "content": (question or "")[:500]}],
            provider_index=provider_index, temperature=0.1, max_tokens=2048,
            module="drawing_classify")
    except Exception:
        result = False
    else:
        txt = (out or "").upper()
        result = "FAST" in txt and "SLOW" not in txt
    if len(_CLASSIFY_CACHE) >= _CLASSIFY_CACHE_MAX:
        _CLASSIFY_CACHE.clear()
    _CLASSIFY_CACHE[ckey] = result
    return result


_FAST_SYSTEM = """你是图纸文本数据摘取与归纳器。只依据用户提供的【图纸文本数据】回答，禁止想象或推断图像内容。
## 硬性要求
- 所有文字、编号、数值、尺寸必须与文本数据原文完全一致，禁止换算、四舍五入、推断或补全
- 若文本数据不足以确定答案（包括必须看图才能回答的部分），只输出标记 {marker}，不要输出其他任何内容
- 先给结论再给说明：开头一两句话直接给出答案（结论），再展开依据
- 中文回答，专业但易懂的工程术语""".format(marker=FAST_MARKER)


async def fast_answer(question: str, context: str, history_msgs: list,
                      llm_service, provider_index: int,
                      max_tokens: int = 4096) -> str | None:
    """快路直答（#2 数值防失真在 system 提示中约束）。
    返回答案文本；文本不足（NEED_IMAGE 标记/空）或异常 → None，调用方降级慢路。"""
    if not context or not context.strip():
        return None
    user_text = f"【图纸文本数据】\n{context}\n\n【问题】{question}"
    try:
        out = await llm_service.chat_complete(
            messages=[{"role": "system", "content": _FAST_SYSTEM}]
                     + list(history_msgs or [])
                     + [{"role": "user", "content": user_text}],
            provider_index=provider_index, temperature=0.3, max_tokens=max_tokens,
            module="drawing_fast")
    except Exception:
        return None
    out = (out or "").strip()
    if not out or FAST_MARKER in out:
        return None
    return out
