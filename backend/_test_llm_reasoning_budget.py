# -*- coding: utf-8 -*-
"""OpenAIProvider 推理模型预算耗尽回归测试（无 pytest 也能跑：python _test_llm_reasoning_budget.py）

生产实锤（2026-10-03 会话 310）：deepseek-flash 是推理模型，reasoning 计入 max_tokens。
set 问答 16384 预算被思考烧光 → content='' + finish_reason=length →
旧代码 `if not content: content = reasoning_content` 把被截断的思考原文
（44962 字符 "The user asks:...Hmm..."）当回答吐给用户。

期望行为：
1. content 为空且 finish=length → 加倍预算重试，拿到正式回答（绝不返回思考原文）
2. finish=stop 但 content 为空（个别模型答案在 reasoning）→ 保留原兜底
3. content 正常 → 单次调用原样返回
4. 重试用尽仍无 content → 返回明确提示文案，不吐思考原文
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import openai

from config import LLMProviderConfig
from services.llm_service import OpenAIProvider

THINKING_MARKER = "The user asks: secret thinking Hmm hmm hmm"


class FakeUsage:
    def model_dump(self):
        return {"prompt_tokens": 1, "completion_tokens": 2}


def make_resp(content, reasoning, finish):
    msg = SimpleNamespace(content=content, reasoning_content=reasoning)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason=finish)],
        usage=FakeUsage(),
    )


class FakeClient:
    """按脚本顺序吐出预设响应，并记录每次调用参数"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        outer = self

        class Completions:
            async def create(self, **kw):
                outer.calls.append(kw)
                if not outer.responses:
                    raise AssertionError("LLM 调用次数超出脚本预期")
                return outer.responses.pop(0)

        self.chat = SimpleNamespace(completions=Completions())


def run_provider(fake, max_tokens=8192):
    orig = openai.AsyncOpenAI
    openai.AsyncOpenAI = lambda **kw: fake
    try:
        p = OpenAIProvider(LLMProviderConfig(
            name="t", provider="deepseek", api_key="x",
            base_url="http://test", model="deepseek-flash"))
        return asyncio.run(p.chat_complete(
            messages=[{"role": "user", "content": "q"}],
            temperature=0.5, max_tokens=max_tokens))
    finally:
        openai.AsyncOpenAI = orig


def test_budget_exhausted_retries_and_returns_answer():
    """核心回归：思考吃光预算 → 加倍重试拿正式回答，不返回思考原文"""
    fake = FakeClient([
        make_resp(None, THINKING_MARKER, "length"),   # 第1次：预算耗尽
        make_resp("二层最东边柱子为KZ1……", "whatever", "stop"),  # 第2次：加倍后成功
    ])
    out = run_provider(fake, max_tokens=8192)
    assert out == "二层最东边柱子为KZ1……", f"应返回正式回答，实际: {out[:100]!r}"
    assert THINKING_MARKER not in out, "思考原文泄漏进回答"
    assert len(fake.calls) == 2, f"应重试1次，实际调用{len(fake.calls)}次"
    assert fake.calls[1]["max_tokens"] > fake.calls[0]["max_tokens"], \
        f"重试应加倍预算: {fake.calls[0]['max_tokens']} -> {fake.calls[1]['max_tokens']}"


def test_stop_with_empty_content_keeps_reasoning_fallback():
    """finish=stop 且 content 空（个别模型答案在 reasoning_content）→ 保留原兜底"""
    fake = FakeClient([make_resp(None, "完整答案在reasoning里", "stop")])
    out = run_provider(fake)
    assert out == "完整答案在reasoning里", f"原兜底被破坏: {out!r}"
    assert len(fake.calls) == 1, "非 length 不应重试"


def test_normal_content_single_call():
    """正常回答：单次调用原样返回，不触发重试"""
    fake = FakeClient([make_resp("正常回答", THINKING_MARKER, "stop")])
    out = run_provider(fake)
    assert out == "正常回答"
    assert len(fake.calls) == 1


def test_retries_exhausted_no_thinking_leak():
    """重试用尽仍无 content → 明确提示文案，绝不返回思考原文"""
    fake = FakeClient([
        make_resp(None, THINKING_MARKER, "length"),
        make_resp(None, THINKING_MARKER, "length"),
        make_resp(None, THINKING_MARKER, "length"),
    ])
    out = run_provider(fake, max_tokens=8192)
    assert THINKING_MARKER not in out, f"思考原文泄漏: {out[:100]!r}"
    assert len(fake.calls) <= 3, f"最多2次重试（共3次调用），实际{len(fake.calls)}"
    assert out and out.strip(), "失败时应给出提示文案而非空值"


ALL_TESTS = [
    test_budget_exhausted_retries_and_returns_answer,
    test_stop_with_empty_content_keeps_reasoning_fallback,
    test_normal_content_single_call,
    test_retries_exhausted_no_thinking_leak,
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
