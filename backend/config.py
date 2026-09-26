"""全局配置（看图兔精简版：只保留 LLM Provider + 识图设置）"""
import json
import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field

# 自动检测路径：开发模式 / PyInstaller 打包模式
if getattr(sys, "frozen", False):
    WEB_ROOT = Path(sys.executable).parent
    BUNDLE_DIR = Path(sys._MEIPASS)
else:
    WEB_ROOT = Path(__file__).resolve().parent.parent
    BUNDLE_DIR = WEB_ROOT

OUTPUT_DIR = WEB_ROOT / "output"
DATA_DIR = WEB_ROOT / "data"

for d in [OUTPUT_DIR, DATA_DIR]:
    d.mkdir(parents=True, exist_ok=True)


class AgentSettings(BaseModel):
    """AI 识图行为设置"""
    drawing_tile_enabled: bool = True  # 分块渲染开关（密集小字图纸自动触发：OCR文本框≥100且中位框高≤40px）
    drawing_pdf_max_pages: int = 3     # 单份PDF图片视觉读取页数上限
    drawing_pdf_text_max: int = 8000   # 文字层注入prompt总量上限(字符)
    drawing_ocr_dpi: int = 150         # 本地OCR渲染精度(无文字层PDF补OCR文字层)
    drawing_ocr_text_max: int = 8000   # OCR文字层注入prompt上限(字符)
    snip_locate_enabled: bool = True   # 定位Agent+Snip局部放大总开关（关闭→回退既有路由链路）
    profile_agent_enabled: bool = True  # 预处理画像/批次关系图开关（关闭→不生成摘要与关系）


class LLMProviderConfig(BaseModel):
    """单个 LLM Provider 配置"""
    name: str
    provider: str  # openai / claude / deepseek / qwen / mimo / kimi / glm / minimax / bailian
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    enabled: bool = True
    supports_vision: bool = False
    thinking_effort: str = "off"


class AsrSettings(BaseModel):
    """语音识别（ASR）设置——默认小米 MiMo TokenPlan 集群"""
    api_key: str = ""
    base_url: str = "https://token-plan-cn.xiaomimimo.com/v1"
    model: str = "mimo-v2.5-asr"
    language: str = "zh"  # auto/zh/en


class AppConfig(BaseModel):
    """应用全局配置"""
    providers: list[LLMProviderConfig] = Field(default_factory=lambda: [
        LLMProviderConfig(name="OpenAI", provider="openai", base_url="https://api.openai.com/v1", model="gpt-4o"),
        LLMProviderConfig(name="Claude", provider="claude", base_url="https://api.anthropic.com/v1", model="claude-sonnet-4-6"),
        LLMProviderConfig(name="DeepSeek", provider="deepseek", base_url="https://api.deepseek.com/v1", model="deepseek-chat"),
        LLMProviderConfig(name="通义千问", provider="qwen", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", model="qwen-max"),
        LLMProviderConfig(name="小米MiMo", provider="mimo", base_url="https://token-plan-cn.xiaomimimo.com/anthropic", model="mimo-v2-pro"),
    ])
    # 识图助手使用的 provider 索引
    drawing_provider_index: int = 0
    agent_settings: AgentSettings = AgentSettings()
    asr: AsrSettings = AsrSettings()


def load_config() -> AppConfig:
    """加载配置，优先从文件读取"""
    config_file = DATA_DIR / "app_config.json"
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 兼容迁移：字段缺失时补默认值
        if "drawing_provider_index" not in data:
            data["drawing_provider_index"] = 0
        if "agent_settings" not in data:
            data["agent_settings"] = AgentSettings().model_dump()
        return AppConfig(**data)
    return AppConfig()


def save_config(config: AppConfig):
    """保存配置到文件"""
    config_file = DATA_DIR / "app_config.json"
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config.model_dump(), f, ensure_ascii=False, indent=2)
