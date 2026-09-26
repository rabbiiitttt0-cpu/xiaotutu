"""QAAgent（窗口B）：只回答不定位。上下文 = 问题 + 生料包 + 历史。

封装最终视觉调用，参数与既有链路一致（T=0.5 / max_tokens=8192）。
"""

MODULE = "drawing"


async def answer(llm_service, provider_index: int, *, system_prompt: str,
                 history_msgs: list, user_content,
                 temperature: float = 0.5, max_tokens: int = 8192) -> str:
    messages = ([{"role": "system", "content": system_prompt}]
                + list(history_msgs or [])
                + [{"role": "user", "content": user_content}])
    return await llm_service.chat_complete(
        messages=messages, provider_index=provider_index,
        temperature=temperature, max_tokens=max_tokens, module=MODULE)
