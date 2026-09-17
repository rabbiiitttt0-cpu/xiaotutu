"""日志及记录查询 API（仅总管理员，include 级 _SUPER 已挂）"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config import DATA_DIR
from db.database import get_db
from db.models.audit_log import AuditLog, LLMCallLog

router = APIRouter()


def _parse_dt(s: Optional[str], default: datetime) -> datetime:
    if not s:
        return default
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except Exception:
            return default


@router.get("/logs")
async def list_audit_logs(
    event_type: Optional[str] = None,
    username: Optional[str] = None,
    keyword: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    """审计日志查询（分页/类型/用户/关键字/时间范围）"""
    q = db.query(AuditLog)
    if event_type:
        q = q.filter(AuditLog.event_type == event_type)
    if username:
        q = q.filter(AuditLog.username.ilike(f"%{username}%"))
    if keyword:
        q = q.filter(AuditLog.detail.ilike(f"%{keyword}%"))
    if start:
        q = q.filter(AuditLog.created_at >= _parse_dt(start, datetime(2000, 1, 1)))
    if end:
        q = q.filter(AuditLog.created_at <= _parse_dt(end, datetime.now() + timedelta(days=1)))
    total = q.count()
    items = (q.order_by(AuditLog.id.desc())
             .offset((page - 1) * page_size).limit(page_size).all())
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r.id, "event_type": r.event_type, "user_id": r.user_id,
                "username": r.username, "detail": r.detail, "ip": r.ip,
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
            }
            for r in items
        ],
    }


@router.get("/event-types")
async def list_event_types(db: Session = Depends(get_db)):
    """审计日志类型去重列表（前端筛选下拉）"""
    rows = db.query(AuditLog.event_type).distinct().all()
    return {"types": [r[0] for r in rows if r[0]]}


@router.get("/llm-calls")
async def list_llm_calls(
    module: Optional[str] = None,
    success: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    """LLM 调用日志查询"""
    q = db.query(LLMCallLog)
    if module:
        q = q.filter(LLMCallLog.module == module)
    if success is not None:
        q = q.filter(LLMCallLog.success == (success.lower() in ("1", "true", "yes", "成功")))
    if start:
        q = q.filter(LLMCallLog.created_at >= _parse_dt(start, datetime(2000, 1, 1)))
    if end:
        q = q.filter(LLMCallLog.created_at <= _parse_dt(end, datetime.now() + timedelta(days=1)))
    total = q.count()
    items = (q.order_by(LLMCallLog.id.desc())
             .offset((page - 1) * page_size).limit(page_size).all())
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r.id, "module": r.module, "provider": r.provider, "model": r.model,
                "username": r.username, "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens, "latency_ms": r.latency_ms,
                "success": r.success, "error": r.error,
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
            }
            for r in items
        ],
    }


@router.get("/errors")
async def list_errors(lines: int = 200, keyword: Optional[str] = None):
    """系统错误日志（读 data/logs/app.log 尾部；最新在前）"""
    log_file = DATA_DIR / "logs" / "app.log"
    if not log_file.exists():
        return {"total": 0, "items": []}
    content = log_file.read_text(encoding="utf-8", errors="ignore")
    all_lines = [l for l in content.split("\n") if l.strip()]
    if keyword:
        all_lines = [l for l in all_lines if keyword in l]
    items = all_lines[-lines:][::-1]
    return {"total": len(all_lines), "items": [{"line": l} for l in items]}


@router.get("/llm-stats")
async def llm_stats(db: Session = Depends(get_db)):
    """LLM 调用汇总（按模块/成功率/token）"""
    rows = db.query(LLMCallLog).all()
    by_module: dict = {}
    total_tokens = 0
    total_calls = 0
    failed = 0
    for r in rows:
        m = by_module.setdefault(r.module, {"calls": 0, "tokens": 0, "failed": 0})
        m["calls"] += 1
        m["tokens"] += (r.prompt_tokens or 0) + (r.completion_tokens or 0)
        if not r.success:
            m["failed"] += 1
            failed += 1
        total_tokens += (r.prompt_tokens or 0) + (r.completion_tokens or 0)
        total_calls += 1
    return {
        "total_calls": total_calls,
        "total_tokens": total_tokens,
        "failed": failed,
        "by_module": by_module,
    }
