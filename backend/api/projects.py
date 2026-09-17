"""项目图纸管理 API

- 超管：项目 CRUD / 成员管理 / zip 上传图纸 / 常用标记 / 删除
- 成员：我的项目 / 图纸列表（常用置顶，可切全部）/ 图纸详情 / 图纸集 / 5 天会话
- 脱敏：成员看到的图纸文字与历史消息均为还原后的真实名称；LLM 侧只见密文
"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.deps import get_current_user, require_super_admin
from auth.models import User
from db.database import get_db
from db.models.project import (
    Project, ProjectMember, ProjectDrawing, ProjectDrawingSet, ProjectSession,
)
from services import project_service
from services.mask_service import load_project_cipher, restore_text

router = APIRouter()


# ==================== 工具 ====================

def _get_project(db: Session, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if not p or not p.is_active:
        raise HTTPException(status_code=404, detail="项目不存在或已停用")
    return p


def _require_member(db: Session, project_id: int, user: User) -> Project:
    """成员校验（超管直通）"""
    p = _get_project(db, project_id)
    if not user.is_super_admin:
        m = db.query(ProjectMember).filter_by(project_id=project_id, user_id=user.id).first()
        if not m:
            raise HTTPException(status_code=403, detail="您不是该项目成员")
    return p


def _drawing_card(d: ProjectDrawing) -> dict:
    return {
        "id": d.id,
        "filename": d.filename,
        "file_type": d.file_type,
        "status": d.status,
        "error": d.error,
        "is_frequent": d.is_frequent,
        "has_image": d.has_image,
        "image_count": d.image_count,
        "cache_file_id": d.cache_file_id,
        "created_at": d.created_at.strftime("%Y-%m-%d %H:%M:%S") if d.created_at else "",
    }


def _restore_session_messages(sess: ProjectSession, pdir) -> list:
    """会话消息（脱敏态存储）→ 还原真实名称后返回给成员"""
    try:
        msgs = json.loads(sess.messages or "[]")
    except Exception:
        return []
    cmap = load_project_cipher(pdir)
    for m in msgs:
        if isinstance(m.get("content"), str):
            m["content"] = restore_text(m["content"], cmap)
    return msgs


def _session_card(s: ProjectSession) -> dict:
    return {
        "id": s.id,
        "title": s.title,
        "drawing_ids": json.loads(s.drawing_ids or "[]"),
        "message_count": len(json.loads(s.messages or "[]")),
        "created_at": s.created_at.strftime("%Y-%m-%d %H:%M:%S") if s.created_at else "",
        "updated_at": s.updated_at.strftime("%Y-%m-%d %H:%M:%S") if s.updated_at else "",
        "expires_at": s.expires_at.strftime("%Y-%m-%d %H:%M:%S") if s.expires_at else "",
    }


# ==================== 超管：项目管理 ====================

@router.get("")
async def list_projects(db: Session = Depends(get_db), _: User = Depends(require_super_admin)):
    projects = db.query(Project).order_by(Project.id.desc()).all()
    out = []
    for p in projects:
        drawings = db.query(ProjectDrawing).filter_by(project_id=p.id).all()
        out.append({
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "is_active": p.is_active,
            "created_at": p.created_at.strftime("%Y-%m-%d %H:%M:%S") if p.created_at else "",
            "member_count": db.query(ProjectMember).filter_by(project_id=p.id).count(),
            "drawing_total": len(drawings),
            "drawing_ready": sum(1 for d in drawings if d.status == "ready"),
        })
    return out


class ProjectIn(BaseModel):
    name: str
    description: str = ""


@router.post("")
async def create_project(data: ProjectIn, db: Session = Depends(get_db),
                         user: User = Depends(require_super_admin)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="项目名不能为空")
    if db.query(Project).filter_by(name=name).first():
        raise HTTPException(status_code=400, detail="项目名已存在")
    p = Project(name=name, description=data.description.strip(), created_by=user.id)
    db.add(p)
    db.commit()
    db.refresh(p)
    from services.audit_log import audit_event
    audit_event("project_create", user_id=user.id, username=user.username, detail=f"新建项目 {name}")
    return {"id": p.id, "name": p.name}


@router.put("/{project_id}")
async def update_project(project_id: int, data: ProjectIn, db: Session = Depends(get_db),
                         _: User = Depends(require_super_admin)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="项目不存在")
    p.name = data.name.strip() or p.name
    p.description = data.description.strip()
    db.commit()
    return {"message": "ok"}


@router.delete("/{project_id}")
async def delete_project(project_id: int, db: Session = Depends(get_db),
                         user: User = Depends(require_super_admin)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="项目不存在")
    for d in db.query(ProjectDrawing).filter_by(project_id=project_id).all():
        project_service.remove_drawing_cache(d)
        db.delete(d)
    db.query(ProjectMember).filter_by(project_id=project_id).delete()
    db.query(ProjectDrawingSet).filter_by(project_id=project_id).delete()
    db.query(ProjectSession).filter_by(project_id=project_id).delete()
    db.delete(p)
    db.commit()
    project_service.remove_project_files(project_id)
    from services.audit_log import audit_event
    audit_event("project_delete", user_id=user.id, username=user.username, detail=f"删除项目 {p.name}")
    return {"message": "已删除"}


# ==================== 超管：成员管理 ====================

@router.get("/{project_id}/members")
async def list_members(project_id: int, db: Session = Depends(get_db),
                       _: User = Depends(require_super_admin)):
    _get_project(db, project_id)
    rows = (db.query(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .filter(ProjectMember.project_id == project_id).all())
    return [{
        "user_id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "joined_at": m.created_at.strftime("%Y-%m-%d %H:%M:%S") if m.created_at else "",
    } for m, u in rows]


class MemberIn(BaseModel):
    user_id: int


@router.post("/{project_id}/members")
async def add_member(project_id: int, data: MemberIn, db: Session = Depends(get_db),
                     _: User = Depends(require_super_admin)):
    _get_project(db, project_id)
    u = db.get(User, data.user_id)
    if not u or not u.is_active:
        raise HTTPException(status_code=400, detail="用户不存在或已禁用")
    if db.query(ProjectMember).filter_by(project_id=project_id, user_id=data.user_id).first():
        raise HTTPException(status_code=400, detail="该用户已是项目成员")
    db.add(ProjectMember(project_id=project_id, user_id=data.user_id))
    db.commit()
    return {"message": "已添加"}


@router.delete("/{project_id}/members/{user_id}")
async def remove_member(project_id: int, user_id: int, db: Session = Depends(get_db),
                        _: User = Depends(require_super_admin)):
    m = db.query(ProjectMember).filter_by(project_id=project_id, user_id=user_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="成员不存在")
    db.delete(m)
    db.commit()
    return {"message": "已移除"}


# ==================== 超管：图纸管理 ====================

@router.post("/{project_id}/drawings/zip")
async def upload_drawings_zip(project_id: int, file: UploadFile = File(...),
                              db: Session = Depends(get_db),
                              _: User = Depends(require_super_admin),
                              user2: User = Depends(get_current_user)):
    """上传图纸压缩包：解压建 pending 记录，后台串行预处理（进度轮询 drawings 列表）"""
    _get_project(db, project_id)
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="请上传 .zip 压缩包")
    content = await file.read()
    if len(content) > 500 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="压缩包超过 500MB 限制")
    try:
        result = project_service.ingest_zip(project_id, content, user2.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.patch("/{project_id}/drawings/{drawing_id}")
async def patch_drawing(project_id: int, drawing_id: int, data: dict,
                        db: Session = Depends(get_db),
                        _: User = Depends(require_super_admin)):
    d = db.query(ProjectDrawing).filter_by(id=drawing_id, project_id=project_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="图纸不存在")
    if "is_frequent" in data:
        d.is_frequent = bool(data["is_frequent"])
    if data.get("filename"):
        d.filename = str(data["filename"]).strip()[:255]
    db.commit()
    return {"message": "ok"}


@router.delete("/{project_id}/drawings/{drawing_id}")
async def delete_drawing(project_id: int, drawing_id: int, db: Session = Depends(get_db),
                         _: User = Depends(require_super_admin)):
    d = db.query(ProjectDrawing).filter_by(id=drawing_id, project_id=project_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="图纸不存在")
    project_service.remove_drawing_cache(d)
    db.delete(d)
    db.commit()
    return {"message": "已删除"}


# ==================== 成员：我的项目与图纸选用 ====================

@router.get("/mine")
async def my_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Project).filter(Project.is_active.is_(True))
    if not user.is_super_admin:
        q = q.join(ProjectMember, ProjectMember.project_id == Project.id) \
             .filter(ProjectMember.user_id == user.id)
    projects = q.order_by(Project.id.desc()).all()
    return [{"id": p.id, "name": p.name, "description": p.description} for p in projects]


@router.get("/{project_id}/drawings")
async def list_project_drawings(project_id: int, scope: str = "frequent",
                                db: Session = Depends(get_db),
                                user: User = Depends(get_current_user)):
    """图纸列表。成员 scope=frequent（默认，近期常用）| all（全部 ready）；
    超管看全部状态（含进度），scope 忽略。"""
    _require_member(db, project_id, user)
    q = db.query(ProjectDrawing).filter_by(project_id=project_id)
    if user.is_super_admin and scope == "admin":
        drawings = q.order_by(ProjectDrawing.id.desc()).all()
    else:
        drawings = q.filter_by(status="ready") \
            .order_by(ProjectDrawing.is_frequent.desc(), ProjectDrawing.id.desc()).all()
        if scope == "frequent":
            drawings = [d for d in drawings if d.is_frequent]
    return [_drawing_card(d) for d in drawings]


@router.get("/{project_id}/drawings/{drawing_id}/info")
async def drawing_info(project_id: int, drawing_id: int, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """图纸解析详情（还原真实名称后给成员展示；LLM 侧用的是脱敏版）"""
    _require_member(db, project_id, user)
    d = db.query(ProjectDrawing).filter_by(id=drawing_id, project_id=project_id).first()
    if not d or d.status != "ready":
        raise HTTPException(status_code=404, detail="图纸不存在或未处理完成")
    ctx_path = project_service.UPLOAD_DIR / f"{d.cache_file_id}.json"
    if not ctx_path.exists():
        raise HTTPException(status_code=404, detail="解析产物缺失，请重新处理")
    info = json.loads(ctx_path.read_text(encoding="utf-8"))
    cmap = load_project_cipher(project_service.project_dir(project_id))
    for key in ("description", "title_block", "ocr_text"):
        if isinstance(info.get(key), str):
            info[key] = restore_text(info[key], cmap)
    for a in info.get("text_annotations") or []:
        if isinstance(a.get("text"), str):
            a["text"] = restore_text(a["text"], cmap)
    info["file_id"] = d.cache_file_id
    return info


# ==================== 成员：图纸集（成员可建，项目共享） ====================

def _set_card(s: ProjectDrawingSet) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "drawing_ids": json.loads(s.drawing_ids or "[]"),
        "created_by": s.created_by,
        "created_at": s.created_at.strftime("%Y-%m-%d %H:%M:%S") if s.created_at else "",
    }


@router.get("/{project_id}/sets")
async def list_sets(project_id: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    _require_member(db, project_id, user)
    sets = db.query(ProjectDrawingSet).filter_by(project_id=project_id) \
        .order_by(ProjectDrawingSet.id.desc()).all()
    return [_set_card(s) for s in sets]


class SetIn(BaseModel):
    name: str
    drawing_ids: list[int] = []


@router.post("/{project_id}/sets")
async def create_set(project_id: int, data: SetIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    _require_member(db, project_id, user)
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="图纸集名称不能为空")
    if not data.drawing_ids:
        raise HTTPException(status_code=400, detail="图纸集至少包含一张图纸")
    s = ProjectDrawingSet(project_id=project_id, name=name[:100],
                          drawing_ids=json.dumps(data.drawing_ids), created_by=user.id)
    db.add(s)
    db.commit()
    db.refresh(s)
    return _set_card(s)


@router.put("/{project_id}/sets/{set_id}")
async def update_set(project_id: int, set_id: int, data: SetIn,
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_member(db, project_id, user)
    s = db.query(ProjectDrawingSet).filter_by(id=set_id, project_id=project_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="图纸集不存在")
    if data.name.strip():
        s.name = data.name.strip()[:100]
    if data.drawing_ids:
        s.drawing_ids = json.dumps(data.drawing_ids)
    db.commit()
    return _set_card(s)


@router.delete("/{project_id}/sets/{set_id}")
async def delete_set(project_id: int, set_id: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    _require_member(db, project_id, user)
    s = db.query(ProjectDrawingSet).filter_by(id=set_id, project_id=project_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="图纸集不存在")
    db.delete(s)
    db.commit()
    return {"message": "已删除"}


# ==================== 成员：项目会话（5 天保留） ====================

@router.get("/{project_id}/sessions")
async def list_sessions(project_id: int, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    _require_member(db, project_id, user)
    sessions = db.query(ProjectSession) \
        .filter_by(project_id=project_id, user_id=user.id) \
        .filter(ProjectSession.expires_at > datetime.now()) \
        .order_by(ProjectSession.updated_at.desc()).all()
    return [_session_card(s) for s in sessions]


@router.get("/{project_id}/sessions/{session_id}")
async def get_session(project_id: int, session_id: int, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    _require_member(db, project_id, user)
    s = db.query(ProjectSession).filter_by(id=session_id, project_id=project_id).first()
    if not s or (s.user_id != user.id and not user.is_super_admin):
        raise HTTPException(status_code=404, detail="会话不存在")
    if s.expires_at < datetime.now():
        raise HTTPException(status_code=404, detail="会话已过期清除")
    card = _session_card(s)
    card["messages"] = _restore_session_messages(s, project_service.project_dir(project_id))
    return card


@router.delete("/{project_id}/sessions/{session_id}")
async def delete_session(project_id: int, session_id: int, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    _require_member(db, project_id, user)
    s = db.query(ProjectSession).filter_by(id=session_id, project_id=project_id).first()
    if not s or (s.user_id != user.id and not user.is_super_admin):
        raise HTTPException(status_code=404, detail="会话不存在")
    db.delete(s)
    db.commit()
    return {"message": "已删除"}
