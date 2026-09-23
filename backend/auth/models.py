"""用户模型（看图兔简化版：无项目成员/授权/模块开关）"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, func

from db.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=True)
    phone = Column(String(20), unique=True, nullable=True)
    hashed_password = Column(String(200), nullable=False)
    display_name = Column(String(100), default="")
    is_super_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    last_login_at = Column(DateTime, nullable=True)
