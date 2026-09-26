"""Agent 基座：独立消息链 + JSON 输出校验 + 失败重试 1 次 + 按 module 独立计量。

llm_call_logs 表按 module 归属（drawing / drawing_route / drawing_locate /
drawing_profile …），用量审计天然分窗口。
"""
import json
import re

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json(text: str):
    """从 LLM 输出中提取 JSON（剥围栏、取最外层 {} 或 []）。失败返回 None。"""
    if not text:
        return None
    t = _FENCE.sub("", text).strip()
    # 先试整体，再退化为最外层括号切片
    for cand in (t,):
        try:
            return json.loads(cand)
        except Exception:
            pass
    pairs = [("{", "}"), ("[", "]")]
    for op, cl in pairs:
        s, e = t.find(op), t.rfind(cl)
        if 0 <= s < e:
            try:
                return json.loads(t[s:e + 1])
            except Exception:
                continue
    return None


async def run_agent(llm_service, provider_index: int, *, module: str,
                    system: str = "", user: str = "",
                    max_tokens: int = 1024, temperature: float = 0.1,
                    expect_json: bool = False):
    """单 Agent 一次任务调用。

    expect_json=True 时返回解析后的 dict/list；输出非法 JSON 自动追问重试 1 次。
    任何异常/失败返回 None（调用方负责回退），绝不抛出打断主链路。
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    attempts = 2 if expect_json else 1
    for i in range(attempts):
        try:
            result = await llm_service.chat_complete(
                messages=list(messages),
                provider_index=provider_index,
                temperature=temperature,
                max_tokens=max_tokens,
                module=module,
            )
        except Exception:
            return None
        if not expect_json:
            return result if (result or "").strip() else None
        parsed = extract_json(result or "")
        if parsed is not None:
            return parsed
        # 追问重试：要求只输出 JSON
        messages = messages + [
            {"role": "assistant", "content": result or ""},
            {"role": "user", "content": "上次输出不是合法JSON。请只输出JSON本体，不要任何解释文字。"},
        ]
    return None
