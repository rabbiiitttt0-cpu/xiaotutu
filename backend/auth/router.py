"""认证路由 - 注册/登录/Token/用户管理（小图兔简化版，无三级权限/授权）"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from db.database import get_db
from .models import User
from .schemas import (
    RegisterRequest, LoginRequest, TokenResponse, RefreshRequest,
    UserInfo, UserUpdateRequest, PasswordChangeRequest,
    AdminUserCreateRequest, AdminUserUpdateRequest,
)
from .service import (
    hash_password, verify_password, create_access_token, create_refresh_token,
    verify_token, get_user_by_login, get_user_by_id,
)
from .deps import get_current_user, require_super_admin

router = APIRouter(prefix="/api/auth", tags=["认证"])


def _user_info(u: User) -> UserInfo:
    return UserInfo(
        id=u.id, username=u.username, email=u.email, phone=u.phone,
        display_name=u.display_name, is_super_admin=u.is_super_admin,
        is_active=u.is_active, created_at=u.created_at, last_login_at=u.last_login_at,
    )


# ===== 注册 =====
@router.post("/register", response_model=UserInfo)
async def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """用户注册（审批制：注册后 is_active=False，管理员启用后方可登录）"""
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    if req.email and db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="邮箱已被注册")
    if req.phone and db.query(User).filter(User.phone == req.phone).first():
        raise HTTPException(status_code=400, detail="手机号已被注册")

    user = User(
        username=req.username, email=req.email, phone=req.phone,
        hashed_password=hash_password(req.password),
        display_name=req.display_name or req.username,
        is_active=False,  # 待审批
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_info(user)


# ===== 登录 =====
@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: Session = Depends(get_db), request: Request = None):
    """登录（用户名/邮箱/手机号 + 密码）"""
    from services.audit_log import audit_event
    client_ip = request.client.host if request and request.client else None
    user = get_user_by_login(db, req.username)
    if not user or not verify_password(req.password, user.hashed_password):
        audit_event("login_failed", username=req.username, detail="用户名或密码错误", ip=client_ip)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        audit_event("login_failed", user_id=user.id, username=user.username,
                    detail="账号未激活或已被禁用", ip=client_ip)
        raise HTTPException(status_code=403, detail="账号未激活或已被禁用，请联系管理员审批")

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    audit_event("login_success", user_id=user.id, username=user.username, ip=client_ip)

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


# ===== 刷新 Token =====
@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(req: RefreshRequest, db: Session = Depends(get_db)):
    payload = verify_token(req.refresh_token, expected_type="refresh")
    if not payload:
        raise HTTPException(status_code=401, detail="Refresh Token无效或已过期")
    user_id = int(payload["sub"])
    user = get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


# ===== 当前用户 =====
@router.get("/me", response_model=UserInfo)
async def get_me(user: User = Depends(get_current_user)):
    return _user_info(user)


@router.put("/me", response_model=UserInfo)
async def update_me(req: UserUpdateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if req.display_name is not None:
        user.display_name = req.display_name
    if req.email is not None:
        if db.query(User).filter(User.email == req.email, User.id != user.id).first():
            raise HTTPException(status_code=400, detail="邮箱已被其他用户使用")
        user.email = req.email
    if req.phone is not None:
        if db.query(User).filter(User.phone == req.phone, User.id != user.id).first():
            raise HTTPException(status_code=400, detail="手机号已被其他用户使用")
        user.phone = req.phone
    db.commit()
    db.refresh(user)
    return _user_info(user)


@router.put("/password")
async def change_password(req: PasswordChangeRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(req.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="原密码错误")
    user.hashed_password = hash_password(req.new_password)
    db.commit()
    return {"message": "密码修改成功"}


# ===== 管理员：用户管理（仅管理员） =====
@router.get("/admin/users", response_model=list[UserInfo])
async def list_users(user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    return [_user_info(u) for u in db.query(User).order_by(User.created_at.desc()).all()]


@router.post("/admin/users", response_model=UserInfo)
async def create_user(req: AdminUserCreateRequest, user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    if req.email and db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="邮箱已存在")
    if req.phone and db.query(User).filter(User.phone == req.phone).first():
        raise HTTPException(status_code=400, detail="手机号已存在")
    new_user = User(
        username=req.username, email=req.email, phone=req.phone,
        hashed_password=hash_password(req.password),
        display_name=req.display_name or req.username,
        is_super_admin=req.is_super_admin,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    from services.audit_log import audit_event
    audit_event("user_create", user_id=user.id, username=user.username,
                detail=f"创建用户 {new_user.username}" + ("（管理员）" if req.is_super_admin else ""))
    return _user_info(new_user)


@router.put("/admin/users/{target_user_id}", response_model=UserInfo)
async def update_user(target_user_id: int, req: AdminUserUpdateRequest,
                      user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if req.display_name is not None:
        target.display_name = req.display_name
    if req.email is not None:
        target.email = req.email
    if req.phone is not None:
        target.phone = req.phone
    if req.is_active is not None:
        target.is_active = req.is_active
    if req.is_super_admin is not None:
        target.is_super_admin = req.is_super_admin
    db.commit()
    db.refresh(target)
    from services.audit_log import audit_event
    audit_event("user_update", user_id=user.id, username=user.username,
                detail=f"编辑用户 {target.username}" + ("（已禁用）" if req.is_active is False else ""))
    return _user_info(target)


@router.delete("/admin/users/{target_user_id}")
async def delete_user(target_user_id: int, user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="不能禁用自己")
    target.is_active = False
    db.commit()
    from services.audit_log import audit_event
    audit_event("user_disable", user_id=user.id, username=user.username,
                detail=f"禁用用户 {target.username}")
    return {"message": "用户已禁用"}


@router.delete("/admin/users/{target_user_id}/permanent")
async def delete_user_permanently(target_user_id: int, user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    if target.is_super_admin:
        raise HTTPException(status_code=400, detail="不能删除管理员账号")
    if target.is_active:
        raise HTTPException(status_code=400, detail="仅可删除已禁用的账号，请先禁用")
    db.delete(target)
    db.commit()
    from services.audit_log import audit_event
    audit_event("user_delete", user_id=user.id, username=user.username,
                detail=f"彻底删除账号 {target.username}")
    return {"message": f"账号 {target.username} 已彻底删除"}
