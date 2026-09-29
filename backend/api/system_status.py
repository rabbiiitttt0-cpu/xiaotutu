"""系统实时状态 API — Agent活动、Token用量、在线时长"""
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.deps import require_super_admin
from auth.models import User
from config import DATA_DIR, load_config, save_config, AppConfig, LLMProviderConfig

router = APIRouter(prefix="/api/system", tags=["系统状态"])

# 全局状态追踪
_start_time = datetime.now()
_agent_activities = []  # [{name, status, started_at, finished_at, tokens}]
_llm_latencies = []  # 最近LLM调用延迟（秒）
_token_log_file = DATA_DIR / "token_usage.json"


def _load_token_log():
    today = datetime.now().strftime("%Y-%m-%d")
    if _token_log_file.exists():
        with open(_token_log_file, encoding="utf-8") as f:
            data = json.load(f)
        return data.get(today, {"tokens": 0, "requests": 0})
    return {"tokens": 0, "requests": 0}


def _save_token_usage(tokens: int):
    today = datetime.now().strftime("%Y-%m-%d")
    data = {}
    if _token_log_file.exists():
        with open(_token_log_file, encoding="utf-8") as f:
            data = json.load(f)
    day_data = data.get(today, {"tokens": 0, "requests": 0})
    day_data["tokens"] += tokens
    day_data["requests"] += 1
    data[today] = day_data
    with open(_token_log_file, "w", encoding="utf-8") as f:
        json.dump(data, f)


def track_llm_latency(seconds: float):
    """记录LLM调用延迟"""
    global _llm_latencies
    _llm_latencies.append(seconds)
    if len(_llm_latencies) > 50:
        _llm_latencies = _llm_latencies[-50:]


def track_agent_activity(name: str, status: str, tokens: int = 0):
    """记录Agent活动（其他模块调用）"""
    global _agent_activities
    now = datetime.now()

    if status == "running":
        _agent_activities.append({
            "name": name, "status": "running",
            "started_at": now.strftime("%H:%M:%S"),
            "finished_at": None, "tokens": 0,
        })
    elif status in ("completed", "failed"):
        for a in _agent_activities:
            if a["name"] == name and a["status"] == "running":
                a["status"] = status
                a["finished_at"] = now.strftime("%H:%M:%S")
                a["tokens"] = tokens
                break

    if tokens > 0:
        _save_token_usage(tokens)

    # 清理超过10分钟的已完成记录
    cutoff = now - timedelta(minutes=10)
    _agent_activities = [
        a for a in _agent_activities
        if a["status"] == "running" or
           (a.get("finished_at") and datetime.strptime(
               f"{now.strftime('%Y-%m-%d')} {a['finished_at']}", "%Y-%m-%d %H:%M:%S") > cutoff)
    ]


@router.get("/status")
async def system_status():
    """获取系统实时状态"""
    online = datetime.now() - _start_time
    hours, remainder = divmod(int(online.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    usage = _load_token_log()

    # LLM平均延迟
    llm_latency = round(sum(_llm_latencies) / len(_llm_latencies) * 1000) if _llm_latencies else 0

    return {
        "online_time": f"{hours}时{minutes}分{seconds}秒",
        "online_seconds": int(online.total_seconds()),
        "today_tokens": usage["tokens"],
        "today_requests": usage["requests"],
        "llm_latency_ms": llm_latency,
        "agent_activities": _agent_activities[-10:],
        "active_count": len([a for a in _agent_activities if a["status"] == "running"]),
    }


@router.get("/llm-providers-public")
async def llm_providers_public():
    """脱敏的 LLM Provider 列表+模块绑定（v4.7.1）：仅名称/型号/多模态标记，供审查等模块的
    模型选择器使用。完整配置（含API Key）走 /api/llm/*（仅总管理员）。"""
    cfg = load_config()
    providers = [
        {
            "index": i,
            "name": p.name,
            "model": p.model,
            "supports_vision": getattr(p, "supports_vision", False),
            "enabled": p.enabled,
            "has_key": bool(p.api_key),
        }
        for i, p in enumerate(cfg.providers)
    ]
    bindings = {
        k: v for k, v in vars(cfg).items()
        if k.endswith("_provider_index")
    }
    return {"providers": providers, "bindings": bindings}


# ==================== 模型设置（仅超管） ====================

class ProviderUpdateRequest(BaseModel):
    """更新 LLM Provider 配置（api_key 传空字符串表示不修改）"""
    name: str
    provider: str
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    enabled: bool = True
    supports_vision: bool = False
    thinking_effort: str = "off"


@router.get("/llm-config")
async def get_llm_config(user: User = Depends(require_super_admin)):
    """完整 LLM 配置（API Key 明文，仅超管）。仅超管。"""
    cfg = load_config()
    providers = []
    for i, p in enumerate(cfg.providers):
        # 明文返回（页面仅超管可见 + 服务绑定 127.0.0.1）：设置页常驻显示 key，
        # 且保存时原样回传，避免空串把已存 key 冲掉
        d = p.model_dump()
        d["index"] = i
        providers.append(d)
    return {
        "providers": providers,
        "drawing_provider_index": cfg.drawing_provider_index,
        "locate_provider_index": cfg.locate_provider_index,
        "profile_provider_index": cfg.profile_provider_index,
        "materials_provider_index": cfg.materials_provider_index,
        "briefing_provider_index": cfg.briefing_provider_index,
        "agent_settings": cfg.agent_settings.model_dump(),
    }


# 各功能 provider 绑定字段（-1 = 跟随识图模型）
_BINDINGS = [
    "locate_provider_index",
    "profile_provider_index",
    "materials_provider_index",
    "briefing_provider_index",
]


@router.put("/llm-config")
async def update_llm_config(body: dict, user: User = Depends(require_super_admin)):
    """整体保存 LLM 配置。仅超管。"""
    cfg = load_config()

    if "providers" in body:
        new_providers = []
        for p_data in body["providers"]:
            # api_key 脱敏值不覆盖原值
            if "api_key" in p_data and "****" in str(p_data["api_key"]):
                idx = p_data.pop("index", None)
                if idx is not None and idx < len(cfg.providers):
                    p_data["api_key"] = cfg.providers[idx].api_key
            p_data.pop("index", None)
            new_providers.append(LLMProviderConfig(**p_data))
        cfg.providers = new_providers

    if "drawing_provider_index" in body:
        idx = body["drawing_provider_index"]
        if not (0 <= idx < len(cfg.providers)):
            raise HTTPException(status_code=400, detail="drawing_provider_index 超出范围")
        cfg.drawing_provider_index = idx

    # 各功能绑定：-1（跟随）或有效索引
    for key in _BINDINGS:
        if key in body:
            idx = body[key]
            if idx != -1 and not (0 <= idx < len(cfg.providers)):
                raise HTTPException(status_code=400, detail=f"{key} 超出范围")
            setattr(cfg, key, idx)

    if "agent_settings" in body:
        from config import AgentSettings
        cfg.agent_settings = AgentSettings(**body["agent_settings"])

    save_config(cfg)
    return {"ok": True}


class ProviderTestRequest(BaseModel):
    """测试单个模型连通性：index=已保存行的索引（api_key 脱敏时回查原值）；
    直接传完整配置则按未保存的新行测试。"""
    index: int | None = None
    name: str = ""
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""


@router.post("/llm-config/test")
async def test_llm_provider(req: ProviderTestRequest, user: User = Depends(require_super_admin)):
    """测试模型连通性（发一条小消息），返回 成功/错误/延迟。仅超管。"""
    from services.llm_service import create_provider

    cfg = load_config()
    if req.index is not None and 0 <= req.index < len(cfg.providers):
        # 已保存行：以已存配置为底，页面上改过的字段覆盖
        p = cfg.providers[req.index].model_dump()
        for k in ("name", "provider", "base_url", "model"):
            v = getattr(req, k)
            if v:
                p[k] = v
        if not req.api_key or "****" in req.api_key:
            pass  # 留空/脱敏 → 用已存 key
        else:
            p["api_key"] = req.api_key
    else:
        # 未保存的新行：全量用请求字段
        if not req.provider:
            raise HTTPException(status_code=400, detail="请先选择模型类型")
        p = {"name": req.name or "未命名", "provider": req.provider,
             "api_key": req.api_key, "base_url": req.base_url, "model": req.model}

    pcfg = LLMProviderConfig(**p)
    if not pcfg.api_key:
        raise HTTPException(status_code=400, detail="未配置 API Key，无法测试")

    provider = create_provider(pcfg)
    ok, msg, latency = await provider.test_connection()
    # 只回前120字，避免整段响应/报错刷屏
    snippet = (msg or "")[:120]
    return {"ok": ok, "message": snippet, "latency_ms": latency,
            "model": pcfg.model, "provider": pcfg.provider}
