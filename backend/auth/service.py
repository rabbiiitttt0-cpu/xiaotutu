"""认证服务 - 密码哈希、Token生成/验证、权限检查"""
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .models import User

# ===== 配置 =====
JWT_SECRET = os.environ.get("JWT_SECRET", "chengyigong-engineering-assistant-secret-key-2026")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120  # 2小时（前端已加401自动续期，双保险）
REFRESH_TOKEN_EXPIRE_DAYS = 3  # 3天（甲方口径：3天一登录）

# ===== 密码哈希 =====
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ===== Token =====
def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "refresh",
        "jti": secrets.token_hex(16),  # 唯一标识，可用于注销
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str, expected_type: str = "access") -> Optional[dict]:
    """验证Token，返回payload或None"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != expected_type:
            return None
        return payload
    except JWTError:
        return None


# ===== 用户查询 =====
def get_user_by_login(db: Session, username: str) -> Optional[User]:
    """通过用户名/邮箱/手机号查找用户"""
    user = db.query(User).filter(User.username == username).first()
    if user:
        return user
    user = db.query(User).filter(User.email == username).first()
    if user:
        return user
    user = db.query(User).filter(User.phone == username).first()
    return user


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


# ===== 项目权限 =====
