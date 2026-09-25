"""看图助手API - DXF图纸上传与问答（v1.1 视觉化升级）

- 解析结果/渲染图/会话全部落盘持久化（修 4 worker 随机 404 + 重启丢失）
- DXF 渲染 PNG 预览 + 视觉问答（文本摘要 + 渲染图一起送多模态模型）
- 用量统计：每次调用记录 token/请求数/估算费用（data/drawing_usage.json）
"""
import base64
import json
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import DATA_DIR
from services.drawing_service import parse_dxf, render_dxf_png
from services.llm_service import LLMService
from config import load_config
from auth.deps import require_super_admin, get_current_user
from auth.models import User
from services import project_service
from services.mask_service import (
    CipherMap, mask_info, mask_text, restore_text,
    load_project_cipher, mask_and_persist,
)

router = APIRouter()

UPLOAD_DIR = DATA_DIR / "drawing_uploads"
SESSIONS_DIR = DATA_DIR / "drawing_sessions"
USAGE_FILE = DATA_DIR / "drawing_usage.json"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

# deepseek-flash 官方费率（$/1M tokens，2026-09 定价页，取峰值保守估算；实际以官方账单为准）
# 峰值：UTC 周一至五 01:00-04:00 / 06:00-10:00，其余为谷值（半价）
COST_RATE_INPUT_MISS = 0.30 / 1e6
COST_RATE_INPUT_HIT = 0.006 / 1e6
COST_RATE_OUTPUT = 1.20 / 1e6


# ==================== 持久化 helpers ====================

def _ctx_path(file_id: str) -> Path:
    return UPLOAD_DIR / f"{file_id}.json"


def _png_path(file_id: str) -> Path:
    return UPLOAD_DIR / f"{file_id}.png"


def _png_paths(file_id: str) -> list[Path]:
    """该图纸的全部渲染图：首页整图（{fid}_hi 或 {fid}.png），其后 {fid}_pN.png
    按页码数值排序（PDF 多页 / 多图框切片）。分块图 {fid}_pN_tRC.png 不算页，排除。"""
    paths = []
    hi = UPLOAD_DIR / f"{file_id}_hi.png"
    if hi.exists():
        paths.append(hi)  # 高清版优先（大图纸默认160dpi只有640px，喂模型/预览都不够）
    else:
        single = _png_path(file_id)
        if single.exists():
            paths.append(single)
    page_pat = re.compile(rf"^{re.escape(file_id)}_p(\d+)$")
    pages = []
    for p in UPLOAD_DIR.glob(f"{file_id}_p*.png"):
        m = page_pat.match(p.stem)
        if m:
            pages.append((int(m.group(1)), p))
    paths.extend(p for _, p in sorted(pages))
    return paths


def _save_context(file_id: str, info: dict):
    """原子写（tmp+replace，防半写文件）"""
    tmp = _ctx_path(file_id).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(_ctx_path(file_id)))


def _load_context(file_id: str) -> dict:
    p = _ctx_path(file_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="图纸不存在，请先上传")
    return json.loads(p.read_text(encoding="utf-8"))


def _record_usage(endpoint: str, with_image: bool, usage: dict | None):
    """记录一次 LLM 调用的 token 用量（usage 为 DeepSeek 响应 usage 字段）"""
    entry = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "endpoint": endpoint,
        "with_image": with_image,
        "prompt_tokens": (usage or {}).get("prompt_tokens") or 0,
        "completion_tokens": (usage or {}).get("completion_tokens") or 0,
        "cache_hit_tokens": (usage or {}).get("prompt_cache_hit_tokens") or 0,
        "cache_miss_tokens": (usage or {}).get("prompt_cache_miss_tokens") or 0,
    }
    try:
        records = json.loads(USAGE_FILE.read_text(encoding="utf-8")) if USAGE_FILE.exists() else []
        records.append(entry)
        # 只留最近 2000 条，防无限增长
        tmp = USAGE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(records[-2000:], ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(USAGE_FILE))
    except Exception:
        pass  # 统计失败不影响主流程


def _image_content(text: str, file_id: str) -> tuple[object, bool]:
    """构造多模态 user content（最多 3 张渲染图：DXF 单张 / PDF 逐页）；
    无渲染图时降级纯文本（返回(content, 是否带图)）"""
    pngs = _png_paths(file_id)[:3]
    if pngs:
        content = [{"type": "text", "text": text}]
        for p in pngs:
            b64 = base64.b64encode(p.read_bytes()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        return (content, True)
    return (text, False)


def _image_content_ex(text: str, file_id: str, info: dict) -> tuple[object, bool]:
    """带分块策略的多模态 content：tiled 图纸 = 整页总览 + 2×2重叠分块（≤7张）"""
    if info.get("tiled"):
        pngs = _png_paths(file_id)
        if not pngs:
            return (text, False)
        tiles = sorted(UPLOAD_DIR.glob(f"{file_id}_p1_t*.png"))[:6]
        content = [{"type": "text", "text": text}]
        for p in [pngs[0]] + tiles:
            b64 = base64.b64encode(p.read_bytes()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        return (content, True)
    return _image_content(text, file_id)


def _vision_note(info: dict, has_image: bool, base: str) -> str:
    """视觉附注：tiled 图纸附加网格分块拼接说明（防跨块信息错位/重叠区误判两处）；
    多图框切片图纸说明页序（首图=整图总览，其后各页=按阅读序的单个图框切片）"""
    if not has_image:
        return ""
    if info.get("tiled"):
        return ("\n\n附：本消息附带图像依次为【整页总览】+【网格分块放大图（2列×2行，"
                "相邻块有15%重叠）】。总览用于定位空间关系；分块重叠区中重复出现的"
                "文字/图元属正常拼接设计，请勿当成两处；跨块信息请对照总览图拼接理解。")
    if info.get("frame_count") and (info.get("image_count") or 0) > 1:
        return (f"\n\n附：该图纸含多个图框已切片，共 {info.get('frame_count')} 个图幅。"
                "图像依次为【整图总览】+【各图幅切片（按上→下、左→右阅读序）】；"
                "问题涉及具体某张图纸时请优先对照对应图幅切片。")
    return base


# ==================== 上传与图纸访问 ====================

@router.post("/upload")
async def upload_dxf(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    """上传图纸（.dxf 直传；.dwg 自动转 DXF：ODA 优先 → LibreDWG 兜底；.pdf 矢量直渲）"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".dxf", ".dwg", ".pdf"):
        raise HTTPException(status_code=400, detail="请上传 .dxf / .dwg / .pdf 格式文件")

    file_id = f"dxf_{uuid.uuid4().hex[:8]}"
    saved_path = UPLOAD_DIR / f"{file_id}{suffix}"
    content = await file.read()
    saved_path.write_bytes(content)

    converter_note = ""
    dxf_path = saved_path
    if suffix == ".dwg":
        from services.drawing_service import convert_dwg_to_dxf
        dxf_path = UPLOAD_DIR / f"{file_id}.dxf"
        ok, msg = convert_dwg_to_dxf(str(saved_path), str(dxf_path))
        if not ok:
            logging.getLogger("app").error("DWG 转换失败: file=%s id=%s msg=%s", file.filename, file_id, msg)
            saved_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400,
                                detail=f"DWG 转换失败（{msg}）。请用 CAD 软件将该图另存为 DXF 后上传")
        converter_note = msg  # 记录转换途径，便于排查兼容性

    try:
        if suffix == ".pdf":
            from services.drawing_service import parse_pdf_drawing, render_pdf_pngs, tile_png, _ai_cfg
            info = parse_pdf_drawing(str(saved_path), display_name=file.filename)
            cfg = _ai_cfg()
            pngs = render_pdf_pngs(str(saved_path), str(UPLOAD_DIR), file_id,
                                   max_pages=cfg["max_pages"])
            info["has_image"] = bool(pngs)
            info["image_count"] = len(pngs)
            # 分块渲染：设置开关开启 且 密集小字触发 → 首页裁 2×2 重叠分块
            if info.get("dense") and cfg["tile_enabled"] and pngs:
                tiles = tile_png(pngs[0], grid=(2, 2))
                if tiles:
                    info["tiled"] = True
            info["layer_count"] = 0
            info["total_entities"] = 0
            info["entity_counts"] = {}
            info["layers"] = []
            info["text_annotations"] = []
        else:
            info = parse_dxf(str(dxf_path), display_name=file.filename)
            # 渲染预览图（失败降级不阻断上传，has_image=False 时问答走纯文本）
            # 注意渲染转换后的 dxf_path，不是 saved_path（DWG 场景 saved_path 是 .dwg 原文）
            png = render_dxf_png(str(dxf_path), str(_png_path(file_id)))
            info["has_image"] = bool(png)
            info["image_count"] = 1 if png else 0
    except Exception as e:
        import traceback
        logging.getLogger("app").error(
            "图纸解析失败: file=%s id=%s suffix=%s error=%s\n%s",
            file.filename, file_id, suffix, e, traceback.format_exc(),
        )
        saved_path.unlink(missing_ok=True)
        dxf_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"图纸解析失败: {str(e)}")
    if converter_note:
        info["converter"] = converter_note

    # 脱敏：文字层敏感信息（单位/人名）→ 密文落盘，对照表存 ctx 内部字段（仅服务端用）。
    # 返回给前端的 info 仍是原文（用户有权看到真实内容，脱敏只针对 LLM 通道）
    cmap = CipherMap()
    masked = mask_info(info, cmap)
    masked["_cipher"] = cmap.to_dict()
    masked["has_image"] = info.get("has_image", False)
    masked["image_count"] = info.get("image_count", 0)
    if info.get("tiled"):
        masked["tiled"] = True

    # 上下文落盘（多 worker / 重启不丢）
    _save_context(file_id, masked)

    from services.audit_log import audit_event
    audit_event("drawing_upload", user_id=user.id, username=user.username,
                detail=f"上传图纸 {file.filename}" + (f"（经{converter_note}转换）" if converter_note else ""))

    return {
        "file_id": file_id,
        "filename": info["filename"],
        "layer_count": info["layer_count"],
        "total_entities": info["total_entities"],
        "entity_counts": info["entity_counts"],
        "layers": info["layers"],
        "text_annotations": info["text_annotations"][:20],
        "description": info["description"],
        "has_image": info["has_image"],
        "image_count": info.get("image_count", 1 if info["has_image"] else 0),
    }


@router.get("/{file_id}/image")
async def drawing_image(file_id: str, fmt: str = ""):
    """图纸渲染预览图（首页；路由 include 级已带登录认证，勿改裸静态挂载）。
    fmt=svg 时优先返回矢量预览（DXF 无限放大不糊；无 SVG 回退 PNG）"""
    if fmt == "svg":
        svg = UPLOAD_DIR / f"{file_id}.svg"
        if not svg.exists():
            # 懒生成：SVG 功能上线前上传的 DXF，首次请求时补渲染（render 同图双出）
            dxf = UPLOAD_DIR / f"{file_id}.dxf"
            if dxf.exists():
                render_dxf_png(str(dxf), str(UPLOAD_DIR / f"{file_id}.png"))
        if svg.exists():
            return FileResponse(str(svg), media_type="image/svg+xml")
        raise HTTPException(status_code=404, detail="该图纸无矢量预览（非DXF或渲染失败）")
    pngs = _png_paths(file_id)
    if not pngs:
        raise HTTPException(status_code=404, detail="预览图不存在（渲染失败或未上传）")
    # 大图纸无 SVG 时的高清预览版（400dpi，_hi.png 不匹配 _p*.png 通配，LLM 不受影响）
    hi = UPLOAD_DIR / f"{file_id}_hi.png"
    if hi.exists():
        return FileResponse(str(hi), media_type="image/png")
    return FileResponse(str(pngs[0]), media_type="image/png")


@router.get("/{file_id}/image/{n}")
async def drawing_image_n(file_id: str, n: int):
    """图纸渲染预览图第 n 页（PDF 多页图纸用）"""
    pngs = _png_paths(file_id)
    if not pngs or n < 1 or n > len(pngs):
        raise HTTPException(status_code=404, detail="预览图不存在")
    return FileResponse(str(pngs[n - 1]), media_type="image/png")


@router.get("/{file_id}/pages")
async def drawing_pages(file_id: str):
    """预览总页数（_hi/总览 + 图框切片），前端翻页器按此懒加载，免逐一 404 探测"""
    return {"count": len(_png_paths(file_id))}


@router.get("/list")
async def list_drawings():
    """获取已上传图纸列表"""
    results = []
    for p in sorted(UPLOAD_DIR.glob("dxf_*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            info = json.loads(p.read_text(encoding="utf-8"))
            results.append({
                "file_id": p.stem,
                "filename": info.get("filename", ""),
                "layer_count": info.get("layer_count", 0),
                "total_entities": info.get("total_entities", 0),
                "has_image": info.get("has_image", False),
            })
        except Exception:
            continue
    return results


# ==================== 会话持久化（前端早已在调，此前后端缺失空转） ====================

@router.post("/sessions")
async def save_session(data: dict):
    """保存/更新会话（有 session_id 则更新，否则新建）"""
    sid = data.get("session_id") or f"sess_{uuid.uuid4().hex[:8]}"
    path = SESSIONS_DIR / f"{sid}.json"
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if path.exists():
        try:
            created_at = json.loads(path.read_text(encoding="utf-8")).get("created_at", created_at)
        except Exception:
            pass
    record = {
        "session_id": sid,
        "file_id": data.get("file_id", ""),
        "filename": data.get("filename", ""),
        "layer_count": data.get("layer_count", 0),
        "total_entities": data.get("total_entities", 0),
        "entity_counts": data.get("entity_counts", {}),
        "layers": data.get("layers", []),
        "text_annotations": data.get("text_annotations", []),
        "description": data.get("description", ""),
        "messages": data.get("messages", []),
        "created_at": created_at,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))
    return {"session_id": sid}


@router.get("/sessions")
async def list_sessions():
    """会话列表（摘要，按更新时间倒序）"""
    results = []
    for p in SESSIONS_DIR.glob("sess_*.json"):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
            results.append({
                "session_id": r.get("session_id", p.stem),
                "filename": r.get("filename", ""),
                "layer_count": r.get("layer_count", 0),
                "total_entities": r.get("total_entities", 0),
                "message_count": len(r.get("messages", [])),
                "created_at": r.get("updated_at") or r.get("created_at", ""),
            })
        except Exception:
            continue
    results.sort(key=lambda x: x["created_at"], reverse=True)
    return results


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """加载完整会话"""
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="会话不存在")
    return json.loads(path.read_text(encoding="utf-8"))


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="会话不存在")
    path.unlink()
    return {"message": "删除成功"}


# ==================== AI 问答 / 材料 / 交底（视觉化） ====================

# ==================== 图纸集（一套多图，方案B 图幅级路由） ====================

def _load_set(set_id: str) -> dict:
    p = UPLOAD_DIR / f"{set_id}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="图纸集不存在，请先上传")
    return json.loads(p.read_text(encoding="utf-8"))


def _sheet_card(info: dict) -> dict:
    """图幅目录卡：路由阶段的唯一依据（纯文本小摘要，便宜）。
    图框标题栏 → 图签/图名类标注 → 正文开头（PDF）。
    （旧实现 body=description 第3行起300字，恰好撞上图层列表，路由全程致盲——
    2026-09-24 边界测试暴露）"""
    from services.drawing_service import _looks_title_block
    tb = (info.get("title_block") or "").strip()
    bits = []
    if tb:
        bits.append("图框：" + tb[:250])
    anns, seen = [], set()
    for t in info.get("text_annotations") or []:
        txt = (t.get("text") or "").strip()
        if txt and txt not in seen:
            seen.add(txt)
            if _looks_title_block(txt):
                anns.append(txt)
    if anns:
        bits.append("图签标注：" + "；".join(anns[:12])[:250])
    if not bits:
        desc = info.get("description", "")
        body = desc.split("\n", 2)[-1][:300] if desc else ""
        if body:
            bits.append(body)
    return {
        "file_id": "",
        "filename": info.get("filename", ""),
        "doc_type": info.get("doc_type", "dxf"),
        "image_count": info.get("image_count", 0),
        "summary": "｜".join(bits)[:500],
    }


@router.post("/sets")
async def create_or_add_set(data: dict):
    """创建图纸集或向既有集追加图幅。body: {file_ids: [...], set_id?: str, name?: str}"""
    file_ids = data.get("file_ids") or []
    if not file_ids and not data.get("set_id"):
        raise HTTPException(status_code=400, detail="file_ids 不能为空")
    set_id = data.get("set_id") or f"set_{uuid.uuid4().hex[:8]}"
    path = UPLOAD_DIR / f"{set_id}.json"
    sheets, created_at = [], datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            sheets = old.get("sheets", [])
            created_at = old.get("created_at", created_at)
        except Exception:
            pass
    existing = {s["file_id"] for s in sheets}
    existing_names = {s.get("filename", "") for s in sheets}
    for fid in file_ids:
        if fid in existing:
            continue
        info = _load_context(fid)  # 坏 id 会 404，及早暴露
        # 同名图纸已在集内则跳过（重复上传会产生新 file_id，按文件名去重防重复图幅）
        if info.get("filename", "") in existing_names:
            continue
        card = _sheet_card(info)
        card["file_id"] = fid
        sheets.append(card)
        existing_names.add(card["filename"])
    rec = {"set_id": set_id, "name": data.get("name", ""), "sheets": sheets, "created_at": created_at}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))
    return rec


@router.get("/sets/{set_id}")
async def get_set(set_id: str):
    return _load_set(set_id)


@router.put("/sets/{set_id}/summary")
async def save_set_summary(set_id: str, data: dict):
    """保存图纸集总览（含图幅关系描述，自动概述生成后由前端回写）——
    后续跨图纸提问时注入 prompt 辅助关系推理"""
    rec = _load_set(set_id)
    rec["set_summary"] = (data.get("summary") or "")[:4000]
    path = UPLOAD_DIR / f"{set_id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))
    return {"message": "ok"}


@router.delete("/sets/{set_id}/sheets/{file_id}")
async def remove_sheet(set_id: str, file_id: str):
    """从图纸集移除单个图幅（前端单文件删除联动）"""
    rec = _load_set(set_id)
    before = len(rec.get("sheets", []))
    rec["sheets"] = [s for s in rec.get("sheets", []) if s.get("file_id") != file_id]
    if len(rec["sheets"]) == before:
        raise HTTPException(status_code=404, detail="图幅不在该图纸集中")
    path = UPLOAD_DIR / f"{set_id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))
    return rec


class ProjectSetRequest(BaseModel):
    project_id: int
    drawing_ids: list[int]


@router.post("/project_set")
async def create_project_set(req: ProjectSetRequest, user: User = Depends(get_current_user)):
    """项目图纸 → 临时图纸集（脱敏目录卡落盘，带 project_id 供输出还原）。
    多图问答/材料/交底复用既有 set 流程；set 记录含 drawing_ids 供会话回写。"""
    from db.database import SessionLocal
    from db.models.project import ProjectMember, ProjectDrawing

    if not req.drawing_ids:
        raise HTTPException(status_code=400, detail="请至少选择一张图纸")
    db = SessionLocal()
    try:
        if not user.is_super_admin:
            m = db.query(ProjectMember).filter_by(
                project_id=req.project_id, user_id=user.id).first()
            if not m:
                raise HTTPException(status_code=403, detail="您不是该项目成员")
        drawings = db.query(ProjectDrawing).filter(
            ProjectDrawing.id.in_(req.drawing_ids),
            ProjectDrawing.project_id == req.project_id).all()
    finally:
        db.close()
    by_id = {d.id: d for d in drawings}
    missing = [i for i in req.drawing_ids if i not in by_id]
    if missing:
        raise HTTPException(status_code=400, detail="部分图纸不存在于该项目")
    not_ready = [d.filename for d in drawings if d.status != "ready"]
    if not_ready:
        raise HTTPException(status_code=400, detail=f"图纸未处理完成：{'、'.join(not_ready)}")

    sheets = []
    for did in req.drawing_ids:
        d = by_id[did]
        info = _load_context(d.cache_file_id)  # 脱敏态上下文
        card = _sheet_card(info)
        card["file_id"] = d.cache_file_id
        sheets.append(card)

    set_id = f"pset_{uuid.uuid4().hex[:8]}"
    rec = {
        "set_id": set_id, "name": "", "sheets": sheets,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "project_id": req.project_id, "drawing_ids": req.drawing_ids,
    }
    path = UPLOAD_DIR / f"{set_id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))
    return {
        "set_id": set_id,
        "sheets": [{"file_id": s["file_id"], "filename": s["filename"],
                    "doc_type": s["doc_type"], "image_count": s["image_count"]}
                   for s in sheets],
    }


async def _route_sheets(sheets: list[dict], question: str, llm_service: "LLMService",
                        provider_index: int) -> tuple[list[dict], str]:
    """图幅级路由：目录卡（纯文本）给模型选 1~4 张相关图幅，返回(选中图幅, 理由)。
    路由失败降级为前 3 张。"""
    catalog = "\n".join(
        f"{i + 1}. [{s['file_id']}] {s['filename']}"
        + (f"｜摘要：{s['summary'][:200]}" if s.get("summary") else "")
        for i, s in enumerate(sheets)
    )
    prompt = f"""用户问题：{question}

以下是一套工程图纸的目录（共 {len(sheets)} 张）。请选出回答该问题最相关的 1~4 张图纸（按相关度排序）。
判据提示：施工图纸较为规范——文件名通常就是图名；图幅右下角图框（标题栏）中含
项目名称、图纸专业、图名、图号、版本等，是判断该图内容与归属的最可靠依据。
如果问题需要综观全套（如"这套图讲了什么"），选最重要的 3 张。
输出JSON：{{"selected": ["file_id1", "file_id2"], "reason": "一句话说明"}}，只输出JSON。

目录：
{catalog}"""
    try:
        result = await llm_service.chat_complete(
            messages=[{"role": "user", "content": prompt}],
            provider_index=provider_index, temperature=0.1, max_tokens=1024, module="drawing_route")
        text = result.strip()
        start, end = text.find("{"), text.rfind("}")
        parsed = json.loads(text[start:end + 1])
        valid = {s["file_id"] for s in sheets}
        picked = [fid for fid in parsed.get("selected", []) if fid in valid][:4]
        if picked:
            by_id = {s["file_id"]: s for s in sheets}
            return [by_id[fid] for fid in picked], parsed.get("reason", "")
    except Exception:
        pass
    return sheets[:3], "路由失败，默认取前3张"


def _set_image_content(text: str, sheets: list[dict], max_images: int = 8) -> tuple[object, bool]:
    """多图幅多模态 content：先每张选中图幅的整图/首页，剩余预算按页轮转补
    分页/切片（原实现只送每图第 1 页，PDF 深页路由与多图框切片的红利吃不到）"""
    queues = [(ps, s["filename"]) for s in sheets
              if (ps := _png_paths(s["file_id"]))]
    if not queues:
        return (text, False)
    content = [{"type": "text", "text": text}]
    attached = 0
    idx = 0
    while attached < max_images:
        progressed = False
        for ps, _fn in queues:
            if idx < len(ps) and attached < max_images:
                b64 = base64.b64encode(ps[idx].read_bytes()).decode("ascii")
                content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
                attached += 1
                progressed = True
        if not progressed:
            break
        idx += 1
    if any(len(ps) > 1 for ps, _ in queues):
        content[0]["text"] += ("\n\n附：图像按图幅分组附送，每幅依次为【整图/首页】→【后续分页或图框切片】"
                               "；PDF 分页中可能含按你的问题检索出的相关深页。")
    return (content, True)


def _sheet_text_context(info: dict, question: str = "", budget: int = 12000) -> str:
    """单图幅文本上下文（替代 description[:3000] 硬截断——description 图层列表在最前，
    图层 >~40 的图文字标注 0 字进上下文，2026-09-24 边界测试 66 题暴露的 L3/L4 主因）。
    优先级：图框标题栏 → 问题检索命中 → 图签/图名类标注 → 去重标注顺序填充 → 图层/实体压缩行。
    预算由 _sheet_budget 按选中图幅数动态分配（图少看细、图多保底）。
    对既有图纸缓存同样生效（不依赖重新预处理）。"""
    from services.drawing_service import _looks_title_block
    parts: list[str] = []
    used = 0

    def _add(line: str) -> bool:
        nonlocal used
        if used + len(line) > budget:
            return False
        parts.append(line)
        used += len(line)
        return True

    tb = (info.get("title_block") or "").strip()
    if tb:
        _add(f"【图框标题栏】{tb[:400]}")

    anns: list[str] = []
    seen: set[str] = set()
    counts: dict[str, int] = {}
    for t in info.get("text_annotations") or []:
        txt = (t.get("text") or "").strip()
        if not txt:
            continue
        counts[txt] = counts.get(txt, 0) + 1
        if txt not in seen:
            seen.add(txt)
            anns.append(txt)

    def _fmt(txt: str) -> str:
        n = counts.get(txt, 1)
        return f"{txt}（×{n}）" if n > 1 else txt

    if not anns:
        # PDF 等无逐条标注的图：description 本身紧凑（图框+前若干页文字层），整段注入
        desc = (info.get("description") or "").strip()
        if desc:
            _add(desc[:budget - used])
        return "\n".join(parts)

    injected: set[str] = set()
    hits = _search_annotations(info, question, limit=40) if question else []
    if hits:
        total = len(info.get("text_annotations") or [])
        _add(f"【与问题相关的标注】（从全量 {total} 条标注中检索命中 {len(hits)} 条）")
        for h in hits:
            if _add("- " + _fmt(h)):
                injected.add(h)
    tb_anns = [a for a in anns if a not in injected and _looks_title_block(a)]
    if tb_anns:
        _add("【图签/图名类标注】")
        for a in tb_anns[:30]:
            if _add("- " + _fmt(a)):
                injected.add(a)
    # 图层/实体压缩统计行（小且关键，先于顺序填充，防被挤掉）
    layers = info.get("layers") or []
    if layers:
        names = "、".join(l.get("name", "") for l in layers[:12])
        suffix = f" 等共{len(layers)}个" if len(layers) > 12 else f" 共{len(layers)}个"
        _add(f"【图层】{names}{suffix}")
    ec = info.get("entity_counts") or {}
    if ec:
        top = "、".join(f"{k}:{v}" for k, v in sorted(ec.items(), key=lambda x: -x[1])[:6])
        _add(f"【实体统计】{top}")
    n_rest = 0
    rest = [a for a in anns if a not in injected]
    for a in rest:
        if not _add("- " + _fmt(a)):
            break
        n_rest += 1
    omitted = len(rest) - n_rest
    if omitted > 0:
        _add(f"- …另有 {omitted} 种标注未注入（可按问题检索补充）")
    return "\n".join(parts)


def _sheet_budget(n_sheets: int) -> int:
    """单图幅文本预算按选中图幅数动态分配：总池 48K 字均分，
    单图上限 30000（只问 1 张时标注全文基本全进，看细），
    下限 8000（图多兜底，不给图幅饿死）。
    1张→30000 / 2张→24000 / 3张→16000 / 4张→12000（路由最多选 4 张）。"""
    if n_sheets <= 0:
        return 12000
    return max(8000, min(30000, 48000 // n_sheets))


def _set_text_context(selected: list[dict], question: str = "") -> str:
    """选中图幅的结构化文本上下文（预算按图幅数动态分配，标注优先于图层列表）"""
    budget = _sheet_budget(len(selected))
    parts = []
    for s in selected:
        try:
            info = _load_context(s["file_id"])
            body = _sheet_text_context(info, question, budget)
            extra = s.get("_routed_pages_text") or ""  # PDF 深页检索补充
            parts.append(f"=== 图幅：{s['filename']} ===\n{body}{extra}")
        except Exception:
            continue
    return "\n\n".join(parts)


def _pdf_route_pages(sheet: dict, question: str, project_id: int = 0,
                     max_new_pages: int = 2, max_page_chars: int = 700) -> str:
    """PDF 深页路由：全页文字层按问题检索 → 命中但未渲染的页按需补渲
    （落盘 {file_id}_pN.png，_png_paths 自动纳入图像通道），返回命中页文本摘录
    （项目模式先按项目对照表脱敏）。无文字层/无命中/非 PDF 返回 ""。
    全页文字首次提取后缓存进 ctx（page_texts，脱敏态），后续问题免重复解析。"""
    if sheet.get("doc_type") != "pdf" or not question:
        return ""
    file_id = sheet.get("file_id", "")
    try:
        info = _load_context(file_id)
    except Exception:
        return ""

    cmap, pdir = None, None
    if project_id:
        from services import project_service
        from services.mask_service import (
            load_project_cipher, save_project_cipher, mask_text)
        pdir = project_service.project_dir(project_id)
        cmap = load_project_cipher(pdir)

    def _locate_src() -> str | None:
        if project_id:
            from db.database import SessionLocal
            from db.models.project import ProjectDrawing
            db = SessionLocal()
            try:
                rec = db.query(ProjectDrawing).filter_by(
                    cache_file_id=file_id, project_id=project_id).first()
                if rec and rec.original_path and Path(rec.original_path).exists():
                    return rec.original_path
            finally:
                db.close()
        p = UPLOAD_DIR / f"{file_id}.pdf"
        return str(p) if p.exists() else None

    src = _locate_src()
    page_texts = info.get("page_texts")
    if page_texts is None:
        if not src:
            info["page_texts"] = []
            _save_context(file_id, info)
            return ""
        try:
            import fitz
            doc = fitz.open(src)
            page_texts = [(pg.get_text("text") or "").strip()[:max_page_chars] for pg in doc]
            info["page_total"] = len(doc)
            doc.close()
        except Exception:
            return ""
        if cmap:
            page_texts = [mask_text(t, cmap) if t else t for t in page_texts]
            save_project_cipher(pdir, cmap)  # 页文本可能引入新实体，回写对照表
        info["page_texts"] = page_texts
        _save_context(file_id, info)
    if not page_texts:
        return ""

    # 二字滑窗打分（与 _search_annotations 同策略）
    qq = re.sub(r"\s+", "", question)
    bigrams = {qq[i:i + 2] for i in range(len(qq) - 1)} - _ANNO_STOP
    scored = []
    for i, t in enumerate(page_texts):
        if not t:
            continue
        hit = sum(1 for b in bigrams if b in t)
        if hit:
            scored.append((hit, i))
    scored.sort(key=lambda x: -x[0])
    picked = sorted(i + 1 for _, i in scored[:3])  # 1-based，按页码顺序注入
    if not picked:
        return ""

    # 命中页里超出已渲染范围的，按需补渲（首轮 max_pages 页之外）
    if src:
        from services.drawing_service import PDF_RENDER_DPI
        import fitz
        new_pages = 0
        for pg in picked:
            png = UPLOAD_DIR / f"{file_id}_p{pg}.png"
            if png.exists() or new_pages >= max_new_pages:
                continue
            try:
                doc = fitz.open(src)
                page = doc[pg - 1]
                page.get_pixmap(matrix=fitz.Matrix(PDF_RENDER_DPI / 72,
                                                   PDF_RENDER_DPI / 72)).save(str(png))
                doc.close()
                new_pages += 1
            except Exception:
                continue

    total = info.get("page_total") or len(page_texts)
    parts = [f"\n\n【深页检索】本图共 {total} 页，按问题命中第 {'、'.join(map(str, picked))} 页："]
    for pg in picked:
        t = page_texts[pg - 1] if pg - 1 < len(page_texts) else ""
        if t:
            parts.append(f"── 第{pg}页 ──\n{t}")
    return "\n".join(parts)


async def _set_llm_call(req_set_id: str, question: str, endpoint: str,
                        prompt_builder, temperature: float, max_tokens: int,
                        snip_image: str = "", history: list | None = None):
    """图纸集 LLM 调用公共流程：路由(>3张)→PDF深页检索→文本上下文+图→调用→记用量。
    prompt_builder(kind_cn, names, ctx) -> system_prompt"""
    srec = _load_set(req_set_id)
    sheets = srec.get("sheets", [])
    if not sheets:
        raise HTTPException(status_code=400, detail="图纸集为空")
    config = load_config()
    llm_service = LLMService()
    pidx = config.drawing_provider_index

    if len(sheets) <= 3:
        selected, route_reason = sheets, ""
    else:
        selected, route_reason = await _route_sheets(sheets, question, llm_service, pidx)

    # PDF 深页路由：按问题检索全页文字层，命中页补渲染 + 文本摘录注入上下文
    proj_id = srec.get("project_id") or 0
    for s in selected:
        try:
            extra = _pdf_route_pages(s, question, proj_id)
            if extra:
                s["_routed_pages_text"] = extra
        except Exception:
            pass  # 深页检索失败不阻断主问答

    ctx = _set_text_context(selected, question)
    # 图纸集总览（含图幅关系描述）注入，辅助跨图纸关系推理
    set_summary = (srec.get("set_summary") or "").strip()
    if set_summary:
        ctx = f"【图纸集总览（含各图幅关系）】\n{set_summary}\n\n{ctx}"
    names = "、".join(s["filename"] for s in selected)
    has_any_image = any(_png_paths(s["file_id"]) for s in selected)
    if snip_image:
        ctx += ("\n\n【用户框选】第1张图是用户在图纸上框选的局部区域截图，问题针对该区域"
                "（如'这样的X还有多少'）——请先在整图中识别同类对象，再对照回答。")
    system_prompt = prompt_builder(len(sheets), names, ctx, has_any_image)

    user_content, with_image = _set_image_content(question, selected)
    if snip_image:
        user_content = _prepend_snip(user_content, snip_image)
        with_image = True
    result = await llm_service.chat_complete(
        messages=[{"role": "system", "content": system_prompt}]
                 + _history_msgs(history or [])
                 + [{"role": "user", "content": user_content}],
        provider_index=pidx, temperature=temperature, max_tokens=max_tokens, module="drawing")
    _record_usage(endpoint, with_image, getattr(llm_service, "last_usage", None))
    referenced = [{"file_id": s["file_id"], "filename": s["filename"]} for s in selected]
    return result, with_image, referenced, route_reason


_ANNO_STOP = {"的是", "什么", "怎么", "哪些", "请问", "一下", "这个", "这些",
              "那个", "那些", "多少", "几个", "如何", "为什么", "告诉", "介绍",
              "图纸", "图中", "这张", "这套", "帮我"}


def _search_annotations(info: dict, question: str, limit: int = 30) -> list[str]:
    """问答时按问题关键词从全量标注中检索补充（RAG-lite，替代硬截断的第3招）：
    中文无空格，取问题的二字滑窗（去停用词）匹配标注文字，命中即注入。"""
    import re
    annotations = info.get("text_annotations") or []
    if not annotations or not question:
        return []
    q = re.sub(r"\s+", "", question)
    bigrams = {q[i:i + 2] for i in range(len(q) - 1)} - _ANNO_STOP
    hits, seen = [], set()
    for t in annotations:
        txt = (t.get("text") or "").strip()
        if txt and txt not in seen and any(b in txt for b in bigrams):
            seen.add(txt)
            hits.append(txt)
            if len(hits) >= limit:
                break
    return hits


class ChatRequest(BaseModel):
    file_id: str = ""
    set_id: str = ""
    question: str
    snip_image: str = ""   # 框选截图（dataURL base64）：用户在预览窗框选局部后针对该区域提问
    project_id: int = 0    # 项目图纸模式：项目对照表脱敏 + 会话上下文
    session_id: int = 0    # 项目会话 id（0=新会话，首次问答后返回）
    drawing_ids: list[int] = []  # 会话记录用：本项目选用的图纸


# ==================== 项目图纸模式：会话/脱敏 helpers ====================

def _project_chat_ctx(req: ChatRequest, user: User):
    """项目模式前置：成员校验 + 会话历史（脱敏态原文）加载。返回 (pdir, history)"""
    from db.database import SessionLocal
    from db.models.project import ProjectMember, ProjectSession

    db = SessionLocal()
    try:
        if not user.is_super_admin:
            m = db.query(ProjectMember).filter_by(
                project_id=req.project_id, user_id=user.id).first()
            if not m:
                raise HTTPException(status_code=403, detail="您不是该项目成员")
        history = []
        if req.session_id:
            s = db.query(ProjectSession).filter_by(
                id=req.session_id, project_id=req.project_id).first()
            if not s or (s.user_id != user.id and not user.is_super_admin):
                raise HTTPException(status_code=404, detail="会话不存在")
            if s.expires_at < datetime.now():
                raise HTTPException(status_code=404, detail="会话已过期清除，请新建会话")
            try:
                history = json.loads(s.messages or "[]")[-10:]  # 上下文窗口：最近 10 条
            except Exception:
                history = []
    finally:
        db.close()
    return project_service.project_dir(req.project_id), history


def _persist_project_session(req: ChatRequest, user: User,
                             question_masked: str, answer_masked: str,
                             drawing_ids: list[int]) -> int:
    """问答落会话（脱敏态存储，展示时还原）+ 刷新 5 天有效期。返回 session_id"""
    from db.database import SessionLocal
    from db.models.project import ProjectSession

    db = SessionLocal()
    try:
        s = None
        if req.session_id:
            s = db.query(ProjectSession).filter_by(
                id=req.session_id, project_id=req.project_id).first()
        if not s:
            s = ProjectSession(
                project_id=req.project_id, user_id=user.id,
                title=req.question[:30],
                drawing_ids=json.dumps(drawing_ids),
                messages="[]",
                expires_at=project_service.session_expiry(),
            )
            db.add(s)
        try:
            msgs = json.loads(s.messages or "[]")
        except Exception:
            msgs = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msgs.append({"role": "user", "content": question_masked, "ts": now})
        msgs.append({"role": "assistant", "content": answer_masked, "ts": now})
        s.messages = json.dumps(msgs, ensure_ascii=False)
        if drawing_ids:
            s.drawing_ids = json.dumps(drawing_ids)
        s.expires_at = project_service.session_expiry()
        db.commit()
        db.refresh(s)
        return s.id
    finally:
        db.close()


def _restore_result(text: str, info: dict | None = None, set_id: str = "",
                    project_id: int = 0) -> str:
    """LLM 输出还原：项目（集/单图）→ 项目对照表；本地上传 → ctx 内对照表；否则原样返回"""
    cmap = None
    if set_id:
        try:
            srec = _load_set(set_id)
        except HTTPException:
            return text
        pid = srec.get("project_id")
        if pid:
            cmap = load_project_cipher(project_service.project_dir(pid))
    elif project_id:
        cmap = load_project_cipher(project_service.project_dir(project_id))
    elif info and info.get("_cipher"):
        cmap = CipherMap(info["_cipher"])
    return restore_text(text, cmap) if cmap else text


def _history_msgs(history: list) -> list:
    """会话历史（脱敏态）→ LLM messages 片段（纯文本）"""
    return [{"role": h.get("role", "user"), "content": h.get("content", "")}
            for h in history if h.get("content")]


def _prepend_snip(content: object, snip_data_url: str) -> object:
    """把框选截图插到多模态 content 最前（第1张图=用户框选区域）"""
    if not snip_data_url.startswith("data:image/"):
        return content
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    elif isinstance(content, list):
        content = list(content)
    content.insert(1 if content and content[0].get("type") == "text" else 0,
                   {"type": "image_url", "image_url": {"url": snip_data_url}})
    return content


@router.post("/chat")
async def drawing_chat(req: ChatRequest, user: User = Depends(get_current_user)):
    """图纸问答：单图(file_id)或图纸集(set_id，>3张自动图幅路由)；
    项目图纸模式（project_id）额外做脱敏/还原 + 5 天会话上下文"""
    if req.set_id:
        # 项目图纸集：集记录里带 project_id → 走脱敏/会话流程
        try:
            srec = _load_set(req.set_id)
        except HTTPException:
            srec = {}
        project_id = req.project_id or srec.get("project_id") or 0
        pdir, history, question_masked = None, [], req.question
        if project_id:
            req.project_id = project_id
            pdir, history = _project_chat_ctx(req, user)
            question_masked = mask_and_persist(req.question, pdir)

        def build_prompt(total, names, ctx, has_img):
            vision_note = ("\n\n附：本消息按上述图幅顺序附带它们的渲染图像，请结合图像与文本信息一起回答。"
                           if has_img else "")
            return f"""你是一位资深的建筑图纸审查专家（高级工程师），拥有30年建筑设计和施工管理经验。

用户上传了一整套工程图纸（共 {total} 张），根据他的问题，已为你选取相关图幅：{names}。
各图幅的结构化信息如下：

{ctx}

## 判读依据提示
- 文件名通常就是图名；图中图框（一般在右下角）含项目名称、图纸专业、图名、
  图号、版本、比例等，是识别图幅身份与内容的最可靠依据，回答图幅归属类问题时优先采用

## 回答要求
- 基于图纸实际数据回答，不编造不存在的信息
- 回答涉及具体数值/构造时，注明依据的是哪张图
- 如果所选图幅不足以回答问题，说明还需要哪张图{vision_note}
- 使用专业但易懂的工程术语，中文回答"""
        result, with_image, referenced, route_reason = await _set_llm_call(
            req.set_id, question_masked, "chat", build_prompt, 0.5, 16384,
            snip_image=req.snip_image, history=history)
        answer = result
        new_session_id = 0
        if project_id:
            cmap = load_project_cipher(pdir)
            answer = restore_text(result, cmap)
            new_session_id = _persist_project_session(
                req, user, question_masked, result, req.drawing_ids)
        return {"answer": answer, "with_image": with_image,
                "referenced": referenced, "route_reason": route_reason,
                "session_id": new_session_id}

    # ===== 单图模式（原有逻辑） =====
    info = _load_context(req.file_id)
    config = load_config()
    llm_service = LLMService()

    # 脱敏：项目模式用项目对照表；本地上传用 ctx 内对照表
    pdir, history, cmap = None, [], None
    if req.project_id:
        pdir, history = _project_chat_ctx(req, user)
        question_masked = mask_and_persist(req.question, pdir)
    elif info.get("_cipher"):
        cmap = CipherMap(info["_cipher"])
        question_masked = mask_text(req.question, cmap)
        info["_cipher"] = cmap.to_dict()
        _save_context(req.file_id, info)  # 用户提问可能引入新实体，回写对照表
    else:
        question_masked = req.question

    has_image = _png_path(req.file_id).exists()
    vision_note = _vision_note(
        info, has_image,
        "\n\n附：本消息附带该图纸的渲染图像，请结合图像与上述结构化信息一起回答。" if has_image else "")
    doc_kind = info.get("doc_type", "dxf")
    kind_cn = "PDF图纸" if doc_kind == "pdf" else "CAD图纸（DXF）"
    system_prompt = f"""你是一位资深的建筑图纸审查专家（高级工程师），拥有30年建筑设计和施工管理经验。

你正在分析一份{kind_cn}。以下是该图纸的结构化信息：

{info['description']}

## 你的能力
1. 根据图层名称和实体类型判断图纸的组成部分
2. 根据文字标注理解图纸的设计意图
3. 分析图纸中各元素的空间关系{vision_note}
4. 解答用户关于图纸内容的任何问题

## 回答要求
- 基于图纸实际数据回答，不编造不存在的信息
- 文件名通常就是图名；图中图框（一般在右下角）含项目名称、图纸专业、图名、
  图号、版本、比例等，是识别图幅身份与内容的最可靠依据，应优先采用
- 如果图纸数据不足以回答问题，说明缺少什么信息
- 使用专业但易懂的工程术语
- 中文回答"""

    # 第3招：按问题从全量标注中检索补充（去重注入之外的遗漏标注在此兜底）
    hits = _search_annotations(info, question_masked)
    if hits:
        total = len(info.get("text_annotations", []))
        system_prompt += (f"\n\n## 与问题相关的标注（从全量 {total} 条标注中检索命中 {len(hits)} 条）\n"
                          + "\n".join(f"- {h}" for h in hits))
    if req.snip_image:
        system_prompt += ("\n\n【用户框选】第1张图是用户在图纸上框选的局部区域截图，问题针对该区域"
                          "（如'这样的X还有多少'）——请先在整图中识别同类对象，再对照回答。")

    user_content, with_image = _image_content_ex(question_masked, req.file_id, info)
    if req.snip_image:
        user_content = _prepend_snip(user_content, req.snip_image)
        with_image = True
    result = await llm_service.chat_complete(
        messages=[
            {"role": "system", "content": system_prompt},
        ] + _history_msgs(history) + [
            {"role": "user", "content": user_content},
        ],
        provider_index=config.drawing_provider_index,
        temperature=0.5,
        max_tokens=8192,
        module="drawing",
    )
    _record_usage("chat", with_image, getattr(llm_service, "last_usage", None))

    # 还原 + 项目会话落库
    new_session_id = 0
    if req.project_id:
        cmap2 = load_project_cipher(pdir)
        answer = restore_text(result, cmap2)
        new_session_id = _persist_project_session(
            req, user, question_masked, result, req.drawing_ids)
    elif cmap:
        answer = restore_text(result, cmap)
    else:
        answer = result

    return {"answer": answer, "with_image": with_image, "session_id": new_session_id}


class MaterialRequest(BaseModel):
    file_id: str = ""
    set_id: str = ""
    project_id: int = 0   # 项目单图模式：输出按项目对照表还原


@router.post("/materials")
async def extract_materials(req: MaterialRequest):
    """材料提取：单图(file_id)或图纸集(set_id，自动路由到材料相关图幅)"""
    if req.set_id:
        def build_prompt(total, names, ctx, has_img):
            vision_note = ("\n\n附：本消息附带所选图幅的渲染图像，请同时从图像中核对材料表、图注。"
                           if has_img else "")
            return f"""你是一位资深的建筑图纸分析专家。用户上传了一整套工程图纸（共 {total} 张），
已为你选取材料信息最相关的图幅：{names}。各图幅信息如下：

{ctx}
{vision_note}
## 任务
提取所选图幅中所有提到的建筑材料，整理成结构化材料清单。

## 输出格式
严格按以下JSON输出，不要包含任何其他文字：
```json
[
  {{"name": "材料名称", "spec": "规格型号", "unit": "单位", "layer": "来源图幅", "note": "备注"}}
]
```

## 提取规则
1. 从文字标注/材料表中提取明确提到的材料名称和规格（文件名通常即图名、图中图框含图名图号，
   "来源图幅"字段填对应图名）
2. 信息不足以确定规格或数量时，对应字段标注"详见图纸"
3. 单位使用工程常用单位（m、m²、m³、kg、t、个、根等）"""
        result, with_image, referenced, route_reason = await _set_llm_call(
            req.set_id, "提取这套图纸中的全部建筑材料，输出材料清单JSON。", "materials",
            build_prompt, 0.3, 16384)
        result = _restore_result(result, set_id=req.set_id)
        materials = _parse_materials_json(result)
        return {"materials": materials, "with_image": with_image,
                "referenced": referenced, "route_reason": route_reason}

    # ===== 单图模式（原有逻辑） =====
    info = _load_context(req.file_id)
    config = load_config()
    llm_service = LLMService()

    has_image = _png_path(req.file_id).exists()
    vision_note = _vision_note(
        info, has_image,
        "\n\n附：本消息附带该图纸的渲染图像，请同时从图像中核对材料表、图注等信息。" if has_image else "")
    system_prompt = f"""你是一位资深的建筑图纸分析专家。请根据以下CAD图纸的结构化信息，提取图中涉及的材料清单。

图纸信息：
{info['description']}
{vision_note}
## 任务
从图纸的文字标注、图层名称、块定义{ '、渲染图像' if has_image else '' }等信息中，提取所有提到的建筑材料，整理成结构化的材料清单。

## 输出格式
请严格按照以下JSON格式输出，不要包含任何其他文字：
```json
[
  {{"name": "材料名称", "spec": "规格型号", "unit": "单位", "layer": "来源图层", "note": "备注"}}
]
```

## 提取规则
1. 从文字标注中提取明确提到的材料名称和规格
2. 从图层名称推断材料类型（如"钢筋"层→钢筋相关材料）
3. 从块定义名称推断可能的构件和材料
4. 如果信息不足以确定规格或数量，在对应字段标注"详见图纸"
5. 单位使用工程常用单位（m、m²、m³、kg、t、个、根等）"""

    user_content, with_image = _image_content_ex("请分析这份图纸中的材料信息，输出材料清单JSON。", req.file_id, info)
    result = await llm_service.chat_complete(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        provider_index=config.drawing_provider_index,
        temperature=0.3,
        max_tokens=8192,
        module="drawing",
    )
    _record_usage("materials", with_image, getattr(llm_service, "last_usage", None))
    result = _restore_result(result, info=info, project_id=req.project_id)

    # 解析LLM返回的JSON（裸JSON/```json围栏/带前后散文 三种形态都兼容：
    # 取第一个 [ 到最后一个 ] 之间的切片解析）
    materials = _parse_materials_json(result)

    return {"materials": materials, "filename": info["filename"], "with_image": with_image}


class BriefingRequest(BaseModel):
    file_id: str = ""
    set_id: str = ""
    project_name: str = ""
    extra_info: str = ""
    project_id: int = 0   # 项目单图模式：输出按项目对照表还原


@router.post("/briefing")
async def generate_briefing(req: BriefingRequest):
    """生成图纸交底文件：单图(file_id)或图纸集(set_id)"""
    if req.set_id:
        project_info = f"项目名称：{req.project_name}" if req.project_name else "项目名称：未指定"
        extra = f"\n补充信息：{req.extra_info}" if req.extra_info else ""

        def build_prompt(total, names, ctx, has_img):
            vision_note = ("\n\n附：本消息附带所选图幅的渲染图像，交底内容请结合图像中的布置、标注。"
                           if has_img else "")
            return f"""你是一位资深的建筑施工技术负责人（高级工程师），拥有30年施工管理经验。

用户上传了一整套工程图纸（共 {total} 张），已为你选取交底相关图幅：{names}。

{project_info}{extra}
各图幅的结构化信息如下：

{ctx}
{vision_note}
## 交底文件格式
请按照以下结构生成交底文件（直接输出内容，不要使用JSON格式）：

一、工程概况
二、图纸主要内容（说明依据了哪些图幅）
三、施工要点（施工顺序、工艺要求）
四、质量控制要点（检验标准和验收要求）
五、安全注意事项
六、材料及设备要求

## 要求
1. 内容要具体、专业，能直接用于施工现场交底
2. 基于图纸实际数据，不编造不存在的信息
3. 使用中文"""
        result, with_image, referenced, route_reason = await _set_llm_call(
            req.set_id, "请根据这套图纸生成施工图纸交底文件。", "briefing",
            build_prompt, 0.5, 16384)
        result = _restore_result(result, set_id=req.set_id)
        return {"briefing": result, "with_image": with_image,
                "referenced": referenced, "route_reason": route_reason}

    # ===== 单图模式（原有逻辑） =====
    info = _load_context(req.file_id)
    config = load_config()
    llm_service = LLMService()

    has_image = _png_path(req.file_id).exists()
    vision_note = _vision_note(
        info, has_image,
        "\n\n附：本消息附带该图纸的渲染图像，交底内容请结合图像中的布置、标注。" if has_image else "")
    project_info = f"项目名称：{req.project_name}" if req.project_name else "项目名称：未指定"
    extra = f"\n补充信息：{req.extra_info}" if req.extra_info else ""

    system_prompt = f"""你是一位资深的建筑施工技术负责人（高级工程师），拥有30年施工管理经验。

请根据以下CAD图纸信息，生成一份用于指导施工的图纸交底文件。

{project_info}
图纸文件：{info['filename']}{extra}

图纸结构化信息：
{info['description']}
{vision_note}
## 交底文件格式
请按照以下结构生成交底文件（直接输出内容，不要使用JSON格式）：

一、工程概况
- 简述工程基本信息和图纸概况

二、图纸主要内容
- 根据图层和实体分析图纸包含的主要内容
- 列出关键构件和尺寸标注

三、施工要点
- 根据图纸内容列出施工中需要注意的关键点
- 包括施工顺序、工艺要求等

四、质量控制要点
- 列出需要重点控制的质量环节
- 包括检验标准和验收要求

五、安全注意事项
- 根据图纸内容列出施工安全注意事项
- 包括高空作业、临边防护等

六、材料及设备要求
- 根据图纸标注列出主要材料和设备要求
- 包括规格、型号等

## 要求
1. 内容要具体、专业，能直接用于施工现场交底
2. 语言简洁明了，便于施工人员理解
3. 基于图纸实际数据，不编造不存在的信息
4. 使用中文"""

    user_content, with_image = _image_content_ex("请根据图纸信息生成施工图纸交底文件。", req.file_id, info)
    result = await llm_service.chat_complete(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        provider_index=config.drawing_provider_index,
        temperature=0.5,
        max_tokens=8192,
        module="drawing",
    )
    _record_usage("briefing", with_image, getattr(llm_service, "last_usage", None))
    result = _restore_result(result, info=info, project_id=req.project_id)

    return {"briefing": result, "filename": info["filename"], "with_image": with_image}


def _parse_materials_json(result: str) -> list:
    """解析材料清单 JSON（裸JSON/```json围栏/带前后散文 三形态兼容，取首[至末]切片）"""
    try:
        text = result.strip()
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
    except Exception:
        pass
    return [{"name": "解析异常", "spec": "-", "unit": "-", "layer": "-", "note": result}]


# ==================== 语音识别（MiMo ASR） ====================

@router.post("/asr")
async def drawing_asr(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    """语音转文字：前端录 wav/mp3 上传，转发小米 MiMo ASR，返回识别文本。

    MiMo ASR 走 OpenAI 兼容 chat/completions（input_audio base64，≤10MB 编码后）。
    TokenPlan key（tp-）需配 token-plan 集群 base_url，见 config.AsrSettings。
    """
    asr_cfg = load_config().asr
    if not asr_cfg.api_key:
        raise HTTPException(status_code=400, detail="语音识别未配置 API Key（data/app_config.json → asr.api_key）")
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="空音频")
    b64 = base64.b64encode(audio).decode("ascii")
    if len(b64) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="音频过大（编码后超过 10MB），请缩短录音")
    fname = (file.filename or "").lower()
    fmt = "mp3" if fname.endswith(".mp3") else "wav"
    payload = {
        "model": asr_cfg.model,
        "messages": [{
            "role": "user",
            "content": [{"type": "input_audio", "input_audio": {
                "data": f"data:audio/{fmt};base64,{b64}"}}],
        }],
        "asr_options": {"language": asr_cfg.language},
    }
    import httpx
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=15.0)) as cli:
            r = await cli.post(
                f"{asr_cfg.base_url.rstrip('/')}/chat/completions",
                headers={"api-key": asr_cfg.api_key,
                         "Authorization": f"Bearer {asr_cfg.api_key}"},
                json=payload)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"语音识别服务返回 {r.status_code}：{r.text[:200]}")
        data = r.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        _record_usage("asr", False, data.get("usage"))
        return {"text": text.strip()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"语音识别调用失败：{type(e).__name__}")


# ==================== 用量统计 ====================

@router.get("/usage")
async def drawing_usage(user: User = Depends(require_super_admin)):
    """识图模块 LLM 用量汇总（仅总管理员可见；费用按峰值费率保守估算，以官方账单为准）"""
    records = json.loads(USAGE_FILE.read_text(encoding="utf-8")) if USAGE_FILE.exists() else []

    def _agg(rows):
        hit = sum(r.get("cache_hit_tokens", 0) for r in rows)
        miss = sum(r.get("cache_miss_tokens", 0) for r in rows)
        out = sum(r.get("completion_tokens", 0) for r in rows)
        return {
            "requests": len(rows),
            "with_image": sum(1 for r in rows if r.get("with_image")),
            "prompt_tokens": sum(r.get("prompt_tokens", 0) for r in rows),
            "completion_tokens": out,
            "cache_hit_tokens": hit,
            "cache_miss_tokens": miss,
            "est_cost_usd": round(hit * COST_RATE_INPUT_HIT + miss * COST_RATE_INPUT_MISS
                                  + out * COST_RATE_OUTPUT, 4),
        }

    by_day: dict[str, list] = {}
    for r in records:
        by_day.setdefault(r["ts"][:10], []).append(r)

    return {
        "total": _agg(records),
        "by_day": [{"date": d, **_agg(rows)} for d, rows in sorted(by_day.items(), reverse=True)[:14]],
        "recent": records[-20:][::-1],
        "cost_note": "费用为峰值费率保守估算（输入未命中$0.30/命中$0.006/输出$1.20 每百万token），实际以 DeepSeek 官方账单为准",
    }
