"""统一日志埋点服务（2026-09-16）

两类日志均写 PG 表（db/models/audit_log.py），仅总管理员可查：
- audit_event：操作审计（登录/上传/生成/审查/管理操作）
- llm_event：LLM 调用明细（模块/provider/token/延迟/成败）

设计要点：
1. 独立 SessionLocal（不依赖调用方事务，埋点处无需传 db；日志失败不影响主流程）
2. 全部 try/except 吞异常——日志模块永不拖垮业务
3. 高频 llm_event 与低频 audit_event 共用此实现，连接用完即还（连接池 pool_size=10）
"""
from db.database import SessionLocal
from db.models.audit_log import AuditLog, LLMCallLog


def audit_event(event_type: str, user_id: int | None = None, username: str | None = None,
                detail: str = "", ip: str | None = None):
    """记录一条操作审计日志"""
    try:
        db = SessionLocal()
        try:
            db.add(AuditLog(
                event_type=event_type, user_id=user_id, username=username,
                detail=detail[:2000], ip=ip,
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        pass  # 日志失败静默，不影响业务


def llm_event(module: str, provider: str | None = None, model: str | None = None,
              user_id: int | None = None, username: str | None = None,
              prompt_tokens: int = 0, completion_tokens: int = 0,
              latency_ms: int = 0, success: bool = True, error: str | None = None):
    """记录一条 LLM 调用日志"""
    try:
        db = SessionLocal()
        try:
            db.add(LLMCallLog(
                module=module, provider=provider, model=model,
                user_id=user_id, username=username,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                latency_ms=latency_ms, success=success, error=(error or "")[:2000],
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        pass  # 日志失败静默，不影响业务
