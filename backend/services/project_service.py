"""项目图纸预处理管线 + 项目会话清理

- 管理员上传 zip → 解压落盘 → 逐文件建 project_drawings(pending) → 入内存队列
- 单线程串行 worker（2C4G 不能与在线问答抢 CPU），逐文件：转换→解析→脱敏→渲染→ready
- 产物双写：原始文件/转换件/对照表 → data/projects/{pid}/；
  脱敏后的解析上下文 + 渲染预览 → data/drawing_uploads/（复用识图问答既有机制，file_id=pd_xxx）
- 重启恢复：processing → failed(中断)，pending → 重新入队
- 会话清理：启动时 + 每 6 小时删除 expires_at 过期的项目会话
"""
import json
import logging
import queue
import shutil
import threading
import time
import uuid
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from config import DATA_DIR

logger = logging.getLogger("app")

PROJECTS_DIR = DATA_DIR / "projects"
UPLOAD_DIR = DATA_DIR / "drawing_uploads"   # 与 api/drawing.py 同目录（产物直接落这里）
SESSION_TTL_DAYS = 5
SUPPORTED_SUFFIX = (".dwg", ".dxf", ".pdf")

_task_queue: "queue.Queue[int]" = queue.Queue()
_worker_started = False


def project_dir(project_id: int) -> Path:
    return PROJECTS_DIR / str(project_id)


def new_cache_file_id() -> str:
    """预处理产物在 drawing_uploads 中的 file_id（随机不可枚举，与上传路径同安全级）"""
    return f"pd_{uuid.uuid4().hex[:8]}"


# ==================== 预处理 worker ====================

def enqueue(drawing_id: int):
    _task_queue.put(drawing_id)


def start_worker():
    """应用启动时调用：恢复中断任务 + 启动串行处理线程"""
    global _worker_started
    if _worker_started:
        return
    _worker_started = True
    _recover_on_startup()
    threading.Thread(target=_worker_loop, daemon=True, name="project-preprocess").start()
    logger.info("[项目预处理] worker 已启动（串行）")


def _recover_on_startup():
    from db.database import SessionLocal
    from db.models.project import ProjectDrawing

    db = SessionLocal()
    try:
        stuck = db.query(ProjectDrawing).filter(ProjectDrawing.status == "processing").all()
        for d in stuck:
            d.status = "failed"
            d.error = "服务重启中断，请删除后重新上传"
        pending = db.query(ProjectDrawing).filter(ProjectDrawing.status == "pending").all()
        db.commit()
        for d in pending:
            enqueue(d.id)
        if stuck or pending:
            logger.info("[项目预处理] 重启恢复：%d 中断置失败，%d 待处理重新入队",
                        len(stuck), len(pending))
    finally:
        db.close()


def _worker_loop():
    while True:
        drawing_id = _task_queue.get()
        try:
            process_drawing(drawing_id)
        except Exception:
            logger.exception("[项目预处理] 图纸 %s 处理异常", drawing_id)
        finally:
            _task_queue.task_done()


def process_drawing(drawing_id: int):
    """单张图纸预处理全流程（任一步失败 → failed + error，不阻断队列）"""
    from db.database import SessionLocal
    from db.models.project import ProjectDrawing
    from services.drawing_service import (
        convert_dwg_to_dxf, parse_dxf, render_dxf_png,
        parse_pdf_drawing, render_pdf_pngs, tile_png, _ai_cfg,
    )
    from services.mask_service import (
        CipherMap, mask_info, load_project_cipher, save_project_cipher,
    )

    db = SessionLocal()
    try:
        rec = db.get(ProjectDrawing, drawing_id)
        if not rec or rec.status not in ("pending",):
            return
        rec.status = "processing"
        db.commit()

        fid = rec.cache_file_id or new_cache_file_id()
        rec.cache_file_id = fid
        pdir = project_dir(rec.project_id)
        pdir.mkdir(parents=True, exist_ok=True)
        suffix = Path(rec.original_path).suffix.lower()

        # 1. DWG → DXF（纯程序转换，无 AI 介入）
        dxf_path = Path(rec.original_path)
        if suffix == ".dwg":
            dxf_path = pdir / f"{fid}.dxf"
            ok, msg = convert_dwg_to_dxf(rec.original_path, str(dxf_path))
            if not ok:
                raise RuntimeError(f"DWG 转换失败（{msg}）")

        # 2. 解析
        if suffix == ".pdf":
            info = parse_pdf_drawing(rec.original_path, display_name=rec.filename)
            info["layer_count"] = 0
            info["total_entities"] = 0
            info["entity_counts"] = {}
            info["layers"] = []
            info["text_annotations"] = []
        else:
            info = parse_dxf(str(dxf_path), display_name=rec.filename)

        # 3. 脱敏：项目级对照表 + 脱敏文字层（LLM 只见密文）
        cmap = load_project_cipher(pdir)
        masked_info = mask_info(info, cmap)
        save_project_cipher(pdir, cmap)
        # 原始解析结果仅服务端留存（不出 API）；errors=replace 兜底其他来源的坏字符
        (pdir / f"{fid}.parsed.json").write_text(
            json.dumps(info, ensure_ascii=False), encoding="utf-8", errors="replace")

        # 4. 渲染预览（落 UPLOAD_DIR，直接复用识图问答/预览机制）
        if suffix == ".pdf":
            cfg = _ai_cfg()
            pngs = render_pdf_pngs(rec.original_path, str(UPLOAD_DIR), fid,
                                   max_pages=cfg["max_pages"])
            masked_info["has_image"] = bool(pngs)
            masked_info["image_count"] = len(pngs)
            if masked_info.get("dense") and cfg["tile_enabled"] and pngs:
                if tile_png(pngs[0], grid=(2, 2)):
                    masked_info["tiled"] = True
        else:
            png = render_dxf_png(str(dxf_path), str(UPLOAD_DIR / f"{fid}.png"))
            masked_info["has_image"] = bool(png)
            masked_info["image_count"] = 1 if png else 0

        # 5. 脱敏上下文落盘（chat/preview 直接读取）
        ctx_tmp = UPLOAD_DIR / f"{fid}.json.tmp"
        ctx_tmp.write_text(json.dumps(masked_info, ensure_ascii=False), encoding="utf-8", errors="replace")
        (UPLOAD_DIR / f"{fid}.json.tmp").replace(UPLOAD_DIR / f"{fid}.json")

        rec.status = "ready"
        rec.has_image = bool(masked_info.get("has_image"))
        rec.image_count = masked_info.get("image_count", 0)
        rec.error = ""
        rec.processed_at = datetime.now()
        db.commit()
        logger.info("[项目预处理] 完成: drawing=%s file=%s", drawing_id, rec.filename)
    except Exception as e:
        rec = db.get(ProjectDrawing, drawing_id)
        if rec:
            rec.status = "failed"
            rec.error = str(e)[:500]
            db.commit()
        logger.exception("[项目预处理] 失败: drawing=%s error=%s", drawing_id, e)
    finally:
        db.close()


# ==================== zip 上传入库 ====================

def ingest_zip(project_id: int, zip_bytes: bytes, uploaded_by: int) -> dict:
    """解压 zip → 支持的图纸建 pending 记录并入队。返回 {created: [...], skipped: [...]}"""
    from db.database import SessionLocal
    from db.models.project import ProjectDrawing

    pdir = project_dir(project_id)
    extract_dir = pdir / "incoming"
    extract_dir.mkdir(parents=True, exist_ok=True)
    zip_path = extract_dir / f"zip_{uuid.uuid4().hex[:8]}.zip"
    zip_path.write_bytes(zip_bytes)

    created, skipped = [], []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                fn = Path(name).name  # 拍平目录层级
                if not fn or fn.startswith(".") or name.endswith("/"):
                    continue
                suffix = Path(fn).suffix.lower()
                if suffix not in SUPPORTED_SUFFIX:
                    skipped.append(fn)
                    continue
                # zip 中文文件名常见 GBK 乱码：cp437 误解码的名称尝试还原
                try:
                    fn_fixed = fn.encode("cp437").decode("gbk")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    fn_fixed = fn
                dest = pdir / f"orig_{uuid.uuid4().hex[:8]}{suffix}"
                dest.write_bytes(zf.read(name))

                db = SessionLocal()
                try:
                    rec = ProjectDrawing(
                        project_id=project_id, filename=fn_fixed,
                        file_type=suffix.lstrip("."), status="pending",
                        original_path=str(dest), uploaded_by=uploaded_by,
                    )
                    db.add(rec)
                    db.commit()
                    db.refresh(rec)
                    created.append({"id": rec.id, "filename": fn_fixed})
                    enqueue(rec.id)
                finally:
                    db.close()
    except zipfile.BadZipFile:
        zip_path.unlink(missing_ok=True)
        raise ValueError("压缩包损坏或不是有效的 zip 文件")
    finally:
        zip_path.unlink(missing_ok=True)
    return {"created": created, "skipped": skipped}


# ==================== 项目会话（5 天保留） ====================

def session_expiry() -> datetime:
    return datetime.now() + timedelta(days=SESSION_TTL_DAYS)


def cleanup_expired_sessions() -> int:
    """删除过期项目会话（只删 DB 记录，图纸产物不受影响）。返回删除数。"""
    from db.database import SessionLocal
    from db.models.project import ProjectSession

    db = SessionLocal()
    try:
        n = db.query(ProjectSession).filter(ProjectSession.expires_at < datetime.now()) \
            .delete(synchronize_session=False)
        db.commit()
        if n:
            logger.info("[项目会话] 清理过期会话 %d 条", n)
        return n
    finally:
        db.close()


def start_session_cleaner():
    """启动时清一次 + 每 6 小时清一次"""
    def _loop():
        while True:
            try:
                cleanup_expired_sessions()
            except Exception:
                logger.exception("[项目会话] 清理异常")
            time.sleep(6 * 3600)
    threading.Thread(target=_loop, daemon=True, name="session-cleaner").start()


def remove_project_files(project_id: int):
    """删除项目时清理产物目录（drawing_uploads 中的缓存由记录删除方处理）"""
    shutil.rmtree(project_dir(project_id), ignore_errors=True)


def remove_drawing_cache(rec):
    """删除单张图纸时清理 drawing_uploads 中的缓存产物"""
    fid = rec.cache_file_id
    if not fid:
        return
    for p in UPLOAD_DIR.glob(f"{fid}*"):
        try:
            p.unlink()
        except OSError:
            pass
