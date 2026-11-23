"""多模型统一调用服务

支持 OpenAI / Claude / DeepSeek / 通义千问 / 小米MiMo
所有Provider实现统一接口：chat_complete(messages, model, temperature, max_tokens) -> str
"""
import asyncio
import time
from abc import ABC, abstractmethod
from typing import Optional

from config import AppConfig, LLMProviderConfig, load_config

# 复用 HTTP 客户端：openai/anthropic 每次调用新建 client 会重建底层连接池，
# 多 Agent 串联（一次问答 3~5 次 LLM 调用）反复 TCP+TLS 握手。按 (api_key, base_url)
# 缓存 client 实例——配置变更（key/url 变）自然换新，无需手动失效。
_openai_clients: dict = {}
_anthropic_clients: dict = {}
_MAX_CLIENTS = 64


def _get_openai_client(api_key: str, base_url: str):
    from openai import AsyncOpenAI
    import httpx
    key = (api_key, base_url)
    client = _openai_clients.get(key)
    if client is None:
        if len(_openai_clients) >= _MAX_CLIENTS:
            _openai_clients.clear()
        client = AsyncOpenAI(api_key=api_key, base_url=base_url,
                             timeout=httpx.Timeout(300.0, connect=30.0))
        _openai_clients[key] = client
    return client


def _get_anthropic_client(api_key: str, base_url: str):
    import anthropic
    key = (api_key, base_url or None)
    client = _anthropic_clients.get(key)
    if client is None:
        if len(_anthropic_clients) >= _MAX_CLIENTS:
            _anthropic_clients.clear()
        client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url or None,
                                          timeout=300.0)
        _anthropic_clients[key] = client
    return client


class LLMProvider(ABC):
    """LLM Provider基类"""

    def __init__(self, config: LLMProviderConfig):
        self.config = config

    @abstractmethod
    async def chat_complete(
        self,
        messages: list[dict],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        ...

    async def test_connection(self) -> tuple[bool, str, int]:
        """测试连通性，返回(成功, 响应/错误, 延迟ms)"""
        start = time.time()
        try:
            result = await self.chat_complete(
                messages=[{"role": "user", "content": "你好，请用一句话介绍你自己。"}],
                temperature=0.7,
                max_tokens=100,
            )
            latency = int((time.time() - start) * 1000)
            return True, result, latency
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            return False, str(e), latency


def _has_vision_images(messages: list) -> bool:
    """检查消息是否包含多模态图片"""
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for item in content:
                if item.get("type") in ("image_url", "image"):
                    return True
    return False


def _convert_images_to_anthropic(messages: list) -> list:
    """将OpenAI格式的image_url转换为Anthropic格式的image"""
    import base64, re
    result = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            new_content = []
            for item in content:
                if item.get("type") == "image_url":
                    url = item["image_url"]["url"]
                    # 解析 data:image/xxx;base64,...
                    match = re.match(r'data:image/(\w+);base64,(.+)', url)
                    if match:
                        new_content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": f"image/{match.group(1)}",
                                "data": match.group(2),
                            }
                        })
                else:
                    new_content.append(item)
            result.append({**msg, "content": new_content})
        else:
            result.append(msg)
    return result


class OpenAIProvider(LLMProvider):
    """OpenAI兼容Provider (OpenAI/DeepSeek/Qwen等，使用OpenAI vision格式)"""

    async def chat_complete(
        self, messages, model="", temperature=0.7, max_tokens=4096
    ) -> str:
        client = _get_openai_client(self.config.api_key, self.config.base_url)
        model_name = model or self.config.model
        import time as _time
        _t0 = _time.time()
        # 思考强度三档（off/low/medium/high）：按厂商映射参数，不支持的自动忽略
        extra = {}
        effort = getattr(self.config, "thinking_effort", "off") or "off"
        if effort in ("low", "medium", "high"):
            p = self.config.provider
            budget = {"low": 1024, "medium": 4096, "high": 16384}[effort]
            if p in ("qwen", "bailian"):
                extra["extra_body"] = {"enable_thinking": True, "thinking_budget": budget}
            elif p == "glm":
                extra["extra_body"] = {"thinking": {"type": "enabled"}}
            elif p == "openai":
                extra["reasoning_effort"] = effort
        async def _create(budget: int):
            return await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=budget,
                **extra,
            )

        resp = await _create(max_tokens)
        # 推理模型（deepseek-flash 等）的 reasoning 计入 max_tokens：预算被思考
        # 烧光时 content 为空、finish_reason=length——绝不能把思考原文当回答
        # 返回（生产事故：2026-10-03 会话310 吐出 4.5 万字符截断思考链）。
        # 加倍预算重试（最多 2 次、封顶 32768），拿到正式回答为止。
        attempts = 0
        while (not resp.choices[0].message.content
               and getattr(resp.choices[0], "finish_reason", "") == "length"
               and attempts < 2 and max_tokens < 32768):
            budget = min(max_tokens * 2, 32768)
            try:
                resp = await _create(budget)
            except Exception:
                break  # 加倍预算被厂商拒绝等 → 按已有响应走下方兜底，不放大故障
            max_tokens = budget
            attempts += 1
        content = resp.choices[0].message.content
        # 透传 token 用量（识图模块用量统计用；各请求独立实例，无并发共享问题）
        try:
            self.last_usage = resp.usage.model_dump() if getattr(resp, "usage", None) else None
        except Exception:
            self.last_usage = None
        # 记录LLM延迟
        try:
            from api.system_status import track_llm_latency
            track_llm_latency(_time.time() - _t0)
        except Exception: pass
        if not content and hasattr(resp.choices[0].message, 'reasoning_content'):
            reasoning = resp.choices[0].message.reasoning_content or ''
            if getattr(resp.choices[0], "finish_reason", "") == "length":
                # 重试用尽仍是 length：思考被截断，返回提示而非思考原文
                return "（模型思考超时，本次未能生成正式回答，请稍后重试或简化问题）"
            # 个别模型（如 MiMo v2.5）content 为空时答案在 reasoning_content
            content = reasoning
        return content


class ClaudeProvider(LLMProvider):
    """Anthropic Claude / MiMo Provider（自动转换图片为Anthropic vision格式）"""

    async def chat_complete(
        self, messages, model="", temperature=0.7, max_tokens=4096
    ) -> str:
        client = _get_anthropic_client(self.config.api_key, self.config.base_url)
        model_name = model or self.config.model

        # 如果消息包含图片，转换为Anthropic格式
        if _has_vision_images(messages):
            messages = _convert_images_to_anthropic(messages)

        # 分离system消息
        system_msg = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg += msg["content"] + "\n"
            else:
                chat_messages.append(msg)

        kwargs = {
            "model": model_name,
            "messages": chat_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system_msg.strip():
            kwargs["system"] = system_msg.strip()

        resp = await client.messages.create(**kwargs)
        try:
            u = getattr(resp, "usage", None)
            self.last_usage = ({"prompt_tokens": getattr(u, "input_tokens", None),
                                "completion_tokens": getattr(u, "output_tokens", None)} if u else None)
        except Exception:
            self.last_usage = None
        # 提取TextBlock内容（MiMo可能返回ThinkingBlock在前）
        for block in resp.content:
            if hasattr(block, "text"):
                return block.text
        return resp.content[0].text if resp.content else ""


# 已知支持多模态的模型名称模式（用于自动检测）
VISION_MODEL_PATTERNS = [
    'gpt-4o', 'gpt-4-turbo', 'gpt-4-vision', 'gemini', 'vision',
    'claude-3', 'claude-3-5', 'claude-sonnet-4', 'claude-opus-4', 'claude-haiku-4',
    'mimo-v2.5', 'mimo-v2-5', 'mimo-v2-5', 'qwen-vl', 'qwenvl',
    'gemini-pro-vision', 'pixtral', 'llava', 'cogvlm',
    'deepseek-flash', 'glm-5.3-flash',  # 2026-09 新增原生视觉模型
]


def auto_detect_vision(provider_name: str, model_name: str) -> bool:
    """根据模型名称自动检测是否支持多模态"""
    combined = f"{provider_name} {model_name}".lower()
    for pattern in VISION_MODEL_PATTERNS:
        if pattern in combined:
            return True
    return False


def create_provider(config: LLMProviderConfig) -> LLMProvider:
    """根据配置创建Provider实例（自动检测多模态能力）"""
    # 自动检测vision能力
    if auto_detect_vision(config.provider, config.model):
        config.supports_vision = True
    # MiMo 如果base_url包含 /anthropic，则走Anthropic格式
    if config.provider == "claude" or (config.provider == "mimo" and "/anthropic" in config.base_url):
        return ClaudeProvider(config)
    # OpenAI/DeepSeek/Qwen/MiMo 走OpenAI兼容接口
    return OpenAIProvider(config)


class LLMService:
    """LLM统一服务"""

    def __init__(self):
        self.config = load_config()

    def reload_config(self):
        self.config = load_config()

    def get_provider(self, index: int) -> LLMProvider:
        """获取指定索引的Provider"""
        if index < 0 or index >= len(self.config.providers):
            raise IndexError(f"Provider索引{index}超出范围(共{len(self.config.providers)}个)")
        config = self.config.providers[index]
        if not config.api_key:
            raise ValueError(
                f"模型「{config.name}」({config.provider}/{config.model}) 未配置API Key。"
                f"请在系统设置→模型管理中为该模型配置API Key，或选择其他已配置Key的模型。"
            )
        return create_provider(config)

    async def chat_complete(
        self,
        messages: list[dict],
        provider_index: int = 0,
        model: str = "",
        temperature: float | None = None,
        max_tokens: int = 4096,
        module: str = "general",
    ) -> str:
        """使用指定Provider调用LLM

        temperature为None时回退使用该Provider配置中的temperature（设置页滑块值）。
        module：调用方标识（agent/review/drawing/disclosure/...），用于 LLM 调用日志归属。
        """
        import time as _time
        _t0 = _time.time()
        pcfg = self.config.providers[provider_index] if 0 <= provider_index < len(self.config.providers) else None
        provider = self.get_provider(provider_index)
        if temperature is None:
            temperature = self.config.providers[provider_index].temperature
        success, err = True, None
        try:
            result = await provider.chat_complete(messages, model, temperature, max_tokens)
        except Exception as e:
            success, err = False, str(e)
            raise
        finally:
            # 透传本次调用的 token 用量（dict 或 None；调用方按需读取，不影响既有返回值）
            usage = getattr(provider, "last_usage", None) or {}
            self.last_usage = usage
            # 记录token用量（旧监控，保留）
            try:
                from api.system_status import track_agent_activity
                track_agent_activity("llm_call", "completed", tokens=max_tokens)
            except Exception:
                pass
            # LLM 调用日志（新审计模块）
            try:
                from services.audit_log import llm_event
                llm_event(
                    module,
                    provider=pcfg.provider if pcfg else None,
                    model=model or (pcfg.model if pcfg else None),
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    latency_ms=int((_time.time() - _t0) * 1000),
                    success=success, error=err,
                )
            except Exception:
                pass
        return result

    async def test_provider(self, index: int) -> tuple[bool, str, int]:
        """测试指定Provider"""
        provider = self.get_provider(index)
        return await provider.test_connection()

    def list_providers(self) -> list[dict]:
        """列出所有Provider配置(脱敏)"""
        result = []
        for i, p in enumerate(self.config.providers):
            result.append({
                "index": i,
                "name": p.name,
                "provider": p.provider,
                "model": p.model,
                "base_url": p.base_url,
                "api_key": bool(p.api_key),
                "api_key_masked": "***" + p.api_key[-4:] if len(p.api_key) > 4 else "***",
                "temperature": p.temperature,
                "max_tokens": p.max_tokens,
                "enabled": p.enabled,
                "supports_vision": auto_detect_vision(p.provider, p.model) or getattr(p, 'supports_vision', False),
            })
        return result
