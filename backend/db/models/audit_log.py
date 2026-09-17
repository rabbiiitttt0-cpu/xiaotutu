"""审计日志 + LLM 调用日志（PG 表，仅总管理员可查）

2026-09-16 王涛需求：完整的日志及记录查询模块，便于系统维护与行为追溯。
复用 quality 的 SQLAlchemy Base/engine（本地 SQLite 兜底 / 云上 PG 自动兼容）。
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, func

from ..database import Base


class AuditLog(Base):
    """操作审计日志：谁在何时做了什么"""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(50), nullable=False, index=True)  # login_success/login_failed/upload_plan/...
    user_id = Column(Integer, nullable=True, index=True)
    username = Column(String(100), nullable=True)  # 冗余存用户名，用户删除后仍可追溯
    detail = Column(Text, nullable=True)
    ip = Column(String(50), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)


class LLMCallLog(Base):
    """LLM 调用日志：模块/provider/token/延迟/成败"""
    __tablename__ = "llm_call_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    module = Column(String(50), nullable=False, index=True)  # agent/review/drawing/disclosure/...
    provider = Column(String(50), nullable=True)
    model = Column(String(100), nullable=True)
    user_id = Column(Integer, nullable=True, index=True)
    username = Column(String(100), nullable=True)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    success = Column(Boolean, default=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
