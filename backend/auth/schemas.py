"""认证相关 Pydantic 模型"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ===== 注册 =====
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)
    email: Optional[str] = None
    phone: Optional[str] = None
    display_name: Optional[str] = None


# ===== 登录 =====
class LoginRequest(BaseModel):
    username: str  # 用户名/邮箱/手机号
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 1800  # 30分钟


class RefreshRequest(BaseModel):
    refresh_token: str


# ===== 用户信息 =====
class UserInfo(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    phone: Optional[str] = None
    display_name: str = ""
    is_super_admin: bool = False
    is_active: bool = True
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None


class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=100)


# ===== 管理员：用户管理 =====
class AdminUserCreateRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)
    email: Optional[str] = None
    phone: Optional[str] = None
    display_name: Optional[str] = None
    is_super_admin: bool = False


class AdminUserUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None
    is_super_admin: Optional[bool] = None


