# -*- coding: utf-8 -*-
"""一期优化回归测试：问题分类双路线 + 快路直答(#1/#2)
无 pytest 也能跑：python _test_fast_route.py

覆盖：
1. 规则分类：纯视觉词→slow、纯图签文字词→fast、冲突→交LLM('')、空问题→''
2. LLM 分类：FAST/SLOW 解析、异常与思考超时文案一律降级慢路
3. 快路直答：正常返回、NEED_IMAGE 标记降级、空上下文不调用、异常降级
4. 单图证据门：文本太薄不尝试、慢路词零 LLM 调用、快路全链路、NEED_IMAGE 降级
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from services.fast_route import FAST_MARKER, rules_classify, llm_classify, fast_answer


class FakeLLM:
    """按脚本吐回复（Exception 实例则抛出），记录每次调用参数"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def chat_complete(self, messages, **kw):
        self.calls.append(dict(kw, messages=messages))
        if not self.replies:
            raise AssertionError("LLM 调用次数超出脚本预期")
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def run(coro):
    import asyncio
    return asyncio.run(coro)


# ---------- 1. 规则分类 ----------

def test_rules_fast():
    for q in ("这套图纸的图号是什么", "请概括这套图纸内容", "设计说明里写了什么",
              "标题栏里的项目名称是什么", "列出图中的文字标注"):
        assert rules_classify(q) == "fast", f"应判 fast: {q!r} → {rules_classify(q)!r}"


def test_rules_slow():
    for q in ("办公楼2楼的最东边有哪些柱子", "左侧的房间有哪些", "一共有多少根柱子"):
        assert rules_classify(q) == "slow", f"应判 slow: {q!r} → {rules_classify(q)!r}"


def test_rules_conflict_and_empty():
    assert rules_classify("说明里关于东边柱子写了什么") == "", "快慢词冲突应交 LLM"
    assert rules_classify("") == "", "空问题应交 LLM（由上层证据门拦截）"
    assert rules_classify("这个结构怎么样") == "", "无特征词应交 LLM"


# ---------- 2. LLM 分类 ----------

def test_llm_classify_parses():
    assert run(llm_classify("问题", FakeLLM(["FAST"]), 0)) is True
    assert run(llm_classify("问题", FakeLLM(["SLOW"]), 0)) is False


def test_llm_classify_safe_fallback():
    """异常/思考超时提示文案 → 一律慢路（误分类代价不对称）"""
    assert run(llm_classify("问题", FakeLLM([RuntimeError("api down")]), 0)) is False
    timeout_msg = "（模型思考超时，本次未能生成正式回答，请稍后重试或简化问题）"
    assert run(llm_classify("问题", FakeLLM([timeout_msg]), 0)) is False
    assert run(llm_classify("问题", FakeLLM(["SLOW，因为需要看图 FAST"]), 0)) is False


# ---------- 3. 快路直答 ----------

def test_fast_answer_ok():
    fake = FakeLLM(["结论：图号为结施-03。依据文本数据…"])
    out = run(fast_answer("图号", "【标题栏】结施-03", [], fake, 0))
    assert out and out.startswith("结论"), f"应返回答案: {out!r}"
    assert fake.calls[0]["module"] == "drawing_fast"
    assert fake.calls[0]["temperature"] == 0.3


def test_fast_answer_marker_degrades():
    """#2 防失真：模型自判文本不足 → None（调用方降级慢路），标记不外泄"""
    fake = FakeLLM([f"前置说明 {FAST_MARKER}"])
    assert run(fast_answer("q", "ctx", [], fake, 0)) is None


def test_fast_answer_empty_context_no_call():
    fake = FakeLLM([])
    assert run(fast_answer("q", "   ", [], fake, 0)) is None
    assert fake.calls == [], "空上下文不应发起 LLM 调用"


def test_fast_answer_exception_degrades():
    fake = FakeLLM([RuntimeError("boom")])
    assert run(fast_answer("q", "ctx", [], fake, 0)) is None


# ---------- 4. 单图证据门 / 全链路（drawing 层） ----------

def test_single_gate_thin_text_no_llm():
    from api.drawing import _try_fast_route_single
    fake = FakeLLM([])  # 任何调用都会 AssertionError
    info = {"description": "短", "title_block": "", "text_annotations": []}
    out = run(_try_fast_route_single(info, "这个结构怎么样", [], fake, 0))
    assert out is None and fake.calls == [], "文本太薄应直接慢路，零 LLM 调用"


def test_single_slow_rule_zero_llm():
    from api.drawing import _try_fast_route_single
    fake = FakeLLM([])
    info = {"description": "x" * 300, "title_block": "图名：平面图",
            "text_annotations": []}
    out = run(_try_fast_route_single(info, "办公楼2楼的最东边有哪些柱子", [], fake, 0))
    assert out is None and fake.calls == [], "慢路词应零 LLM 调用直接放行"


def test_single_fast_path_full():
    from api.drawing import _try_fast_route_single
    fake = FakeLLM(["结论：图号为结施-05。"])
    info = {"description": "x" * 300, "title_block": "图号：结施-05",
            "text_annotations": [{"text": "结施-05"}, {"text": "平面图"}]}
    out = run(_try_fast_route_single(info, "图纸的图号是什么", [], fake, 0))
    assert out == "结论：图号为结施-05。", f"快路全链路失败: {out!r}"
    # 规则已判 fast，不应再调用分类器：只允许 1 次调用（快路直答）
    assert len(fake.calls) == 1 and fake.calls[0]["module"] == "drawing_fast"


def test_single_fast_marker_degrades():
    from api.drawing import _try_fast_route_single
    fake = FakeLLM([FAST_MARKER])
    info = {"description": "x" * 300, "title_block": "图名：平面图",
            "text_annotations": []}
    out = run(_try_fast_route_single(info, "请概括这张图纸", [], fake, 0))
    assert out is None, "NEED_IMAGE 应降级慢路"


ALL_TESTS = [
    test_rules_fast,
    test_rules_slow,
    test_rules_conflict_and_empty,
    test_llm_classify_parses,
    test_llm_classify_safe_fallback,
    test_fast_answer_ok,
    test_fast_answer_marker_degrades,
    test_fast_answer_empty_context_no_call,
    test_fast_answer_exception_degrades,
    test_single_gate_thin_text_no_llm,
    test_single_slow_rule_zero_llm,
    test_single_fast_path_full,
    test_single_fast_marker_degrades,
]

if __name__ == "__main__":
    failed = 0
    for t in ALL_TESTS:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(ALL_TESTS) - failed}/{len(ALL_TESTS)} passed")
    sys.exit(1 if failed else 0)
