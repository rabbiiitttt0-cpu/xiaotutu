"""项目图纸管理数据模型（项目/成员/图纸/图纸集/项目会话）"""
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, ForeignKey,
    UniqueConstraint, func,
)

from db.database import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(500), default="")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())


class ProjectMember(Base):
    """项目成员（多对多：一个用户可属多个项目）"""
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=func.now())


class ProjectDrawing(Base):
    """项目图纸：上传后异步预处理，status 驱动进度展示"""
    __tablename__ = "project_drawings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(10), default="")           # dwg / dxf / pdf
    status = Column(String(20), default="pending")       # pending/processing/ready/failed
    error = Column(Text, default="")
    is_frequent = Column(Boolean, default=False)         # 近期常用（置顶展示）
    original_path = Column(String(500), default="")      # 原始文件落盘路径
    cache_file_id = Column(String(40), default="")       # 预处理产物在 drawing_uploads 的 file_id
    has_image = Column(Boolean, default=False)
    image_count = Column(Integer, default=0)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    processed_at = Column(DateTime, nullable=True)


class ProjectDrawingSet(Base):
    """图纸集：成员可建，项目内共享（一次问答常用的一组图纸）"""
    __tablename__ = "project_drawing_sets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    drawing_ids = Column(Text, default="[]")             # JSON 数组，保序
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())


class ProjectSession(Base):
    """项目会话：整体（所选图纸+对话+上下文）保留 5 天，活跃刷新 expires_at"""
    __tablename__ = "project_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), default="")
    drawing_ids = Column(Text, default="[]")             # JSON 数组
    messages = Column(Text, default="[]")                # JSON 数组（脱敏态原文，展示时还原）
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    expires_at = Column(DateTime, nullable=False, index=True)
