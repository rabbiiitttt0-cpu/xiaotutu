"""项目图纸预处理管线 + 项目会话清理

- 管理员上传 zip → 解压落盘 → 逐文件建 project_drawings(pending) → 入内存队列
- 单线程串行 worker（2C4G 不能与在线问答抢 CPU），逐文件：转换→解析→脱敏→渲染→ready
- 产物双写：原始文件/转换件/对照表 → data/projects/{pid}/；
  脱敏后的解析上下文 + 渲染预览 → data/drawing_uploads/（复用识图问答既有机制，file_id=pd_xxx）
- 重启恢复：processing → failed(中断)，pending → 重新入队
- 会话清理：启动时 + 每 6 小时删除 expires_at 过期的项目会话
"""
import contextlib
import json
import logging
import multiprocessing
import os
import queue
import shutil
import threading
import time
import uuid
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from config import DATA_DIR

# spawn 子进程只 import 本模块时，metadata 里没有 users 表，
# flush project_drawings 的外键会炸 NoReferencedTableError（2026-09-23 生产踩过）。
# 主进程因 main.py 链式 import 不会缺，这里兜的是子进程路径。
import auth.models  # noqa: F401

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
    _sweep_orphan_renders()
    _recover_on_startup()
    threading.Thread(target=_worker_loop, daemon=True, name="project-preprocess").start()
    logger.info("[项目预处理] worker 已启动（串行）")


def _sweep_orphan_renders():
    """杀掉上一代 worker 遗留的 preprocess-* 渲染子进程。

    worker 被杀时其渲染子进程会被 init 收养继续跑（daemon 只在父正常退出时生效），
    白占 CPU/内存（2026-09-23 实测遗留进程跑满 15 分钟 + 2GB）。靠 comm 名匹配：
    渲染子进程名固定 preprocess-{id}，Linux comm 截断到 15 字符，前缀匹配足够。
    """
    try:
        procs = list(Path("/proc").iterdir())
    except OSError:
        return  # 非 Linux（本地 Windows 开发）无 /proc
    killed = 0
    for p in procs:
        if not p.name.isdigit():
            continue
        try:
            comm = (p / "comm").read_text().strip()
            if not comm.startswith("preprocess-"):
                continue
            # 只杀真孤儿（父进程已死、被 init 收养）；存活 worker 的合法渲染不碰。
            # stat 格式：pid (comm) state ppid ...，comm 可能含空格，从最后一个 ')' 后解析
            raw = (p / "stat").read_text()
            fields = raw[raw.rindex(")") + 2:].split()
            if int(fields[1]) != 1:  # ppid
                continue
            os.kill(int(p.name), 9)
            killed += 1
        except (OSError, ValueError, IndexError):
            continue
    if killed:
        logger.warning("[项目预处理] 清扫上一代遗留渲染进程 %d 个", killed)


RESTART_INTERRUPT_ERROR = "服务重启中断，请删除后重新上传"

# ==================== 崩溃隔离（2026-09-23 生产事故加固） ====================
# 事故：某 57MB 毒丸 DXF 渲染时吃光容器内存 → cgroup OOM 杀 uvicorn worker
# → 重启恢复把同一张图重新排队 → 无限循环（一晚崩 40+ 次，残留 197 个 57MB 孤儿 DXF）。
# 加固三条：
# 1. 单图处理放 spawn 子进程：OOM 只杀渲染子进程，父进程存活补标 failed，不再死循环。
# 2. 跨进程文件锁：两个 uvicorn worker 各有一条串行线程，不加锁会并行渲染两张图，
#    峰值内存翻倍、OOM 容易杀到 worker 本体；加锁后全机任意时刻只渲染一张。
# 3. 单图超时 15 分钟：超时 terminate，标 failed，队列继续走。
DRAWING_TIMEOUT_SEC = 900
# 锁文件自愈：持锁方用心跳刷新 mtime（10s 一次），等锁方 60s 无心跳即判定持锁方死亡并接管。
# 不能再用「固定 20 分钟」——那是一次真实事故里的停摆时长（2026-09-23 16:01-16:21）。
LOCK_STALE_SEC = 60
_LOCK_HEARTBEAT_SEC = 10
PREPROCESS_LOCK = DATA_DIR / "preprocess.lock"
# 图框切片会给每张 DXF 多一次全图渲染（大图耗时接近翻倍）。
# 全量部署（2026-09-23）起开启：矢量×OCR 双重判定，失败自动降级单页。
FRAME_SLICE_ENABLED = True


def _run_isolated(drawing_id: int):
    """在 spawn 子进程里跑单图全流程；崩溃/超时由父进程兜底标 failed。"""
    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(target=_child_process_drawing, args=(drawing_id,), daemon=True,
                       name=f"preprocess-{drawing_id}")
    proc.start()
    proc.join(DRAWING_TIMEOUT_SEC)
    if proc.is_alive():
        proc.terminate()
        proc.join(10)
        if proc.is_alive():
            proc.kill()
            proc.join(5)
        _fail_and_cleanup(drawing_id, f"处理超时（>{DRAWING_TIMEOUT_SEC // 60} 分钟），已终止")
        return
    if proc.exitcode != 0:
        # process_drawing 自身已兜底所有业务异常（标 failed 后子进程以 0 退出），
        # 非零退出码 ≈ 被 OOM/信号杀死——补标 failed，绝不能留在 processing 等重启重排。
        _fail_and_cleanup(drawing_id,
                          f"处理进程异常退出（exit={proc.exitcode}，可能内存超限）")


def _child_process_drawing(drawing_id: int):
    # XT_CRASH_TEST：崩溃隔离演练开关（设 "137" 等退出码即模拟被 OOM 杀死），仅排障用
    _crash = os.environ.get("XT_CRASH_TEST")
    if _crash:
        os._exit(int(_crash))
    # 父进程被杀后，900s 超时就没人执行了——子进程自带定时炸弹，到点必死。
    # 父活着时父先 terminate 子进程，定时器到点进程已不存在，无副作用。
    timer = threading.Timer(DRAWING_TIMEOUT_SEC + 120, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        process_drawing(drawing_id)
    except Exception:
        # 防御：process_drawing 理论上自己吞掉所有异常，这里只兜 import/启动期异常
        logger.exception("[项目预处理] 子进程启动期异常 drawing=%s", drawing_id)
        raise


def _fail_and_cleanup(drawing_id: int, error: str):
    """把仍挂在 processing 的图补标 failed，并删除转换中间件 DXF（防再囤孤儿）。"""
    from db.database import SessionLocal
    from db.models.project import ProjectDrawing

    db = SessionLocal()
    try:
        rec = db.get(ProjectDrawing, drawing_id)
        if rec:
            if rec.status == "processing":
                rec.status = "failed"
                rec.error = error
                db.commit()
                logger.warning("[项目预处理] 已标失败: drawing=%s error=%s", drawing_id, error)
            if rec.cache_file_id:
                try:
                    (project_dir(rec.project_id) / f"{rec.cache_file_id}.dxf").unlink(missing_ok=True)
                except OSError:
                    pass
    finally:
        db.close()


@contextlib.contextmanager
def _preprocess_lock():
    """跨进程互斥：全机任意时刻只处理一张图。持锁 worker 死亡后 60s 内由心跳超时接管。"""
    while True:
        try:
            fd = os.open(str(PREPROCESS_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - PREPROCESS_LOCK.stat().st_mtime > LOCK_STALE_SEC:
                    PREPROCESS_LOCK.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            time.sleep(2)
    stop = threading.Event()
    threading.Thread(target=_lock_heartbeat, args=(stop,), daemon=True,
                     name="lock-heartbeat").start()
    try:
        yield
    finally:
        stop.set()
        try:
            PREPROCESS_LOCK.unlink(missing_ok=True)
        except OSError:
            pass


def _lock_heartbeat(stop: threading.Event):
    """持锁期间每 10s 刷新锁文件 mtime；worker 死亡 → 心跳停 → 60s 后他方接管。"""
    while not stop.wait(_LOCK_HEARTBEAT_SEC):
        try:
            os.utime(PREPROCESS_LOCK, None)
        except OSError:
            return


def _recover_on_startup():
    from db.database import SessionLocal
    from db.models.project import ProjectDrawing

    db = SessionLocal()
    try:
        # 重启非破坏性：中断的 processing 直接重新排队（原来是置 failed 要人工重传，
        # 但每次发版重启都会批量误杀在途图纸）。已置 failed 且错误是重启中断的也一并重排。
        requeue = db.query(ProjectDrawing).filter(
            (ProjectDrawing.status == "processing")
            | ((ProjectDrawing.status == "failed")
               & (ProjectDrawing.error == RESTART_INTERRUPT_ERROR))
        ).all()
        for d in requeue:
            d.status = "pending"
            d.error = None
        # SessionLocal 是 autoflush=False：必须先 commit 再查 pending，
        # 否则下面的查询读到的是旧状态，入队 0 条（2026-09-18 生产踩过）
        db.commit()
        pending = db.query(ProjectDrawing).filter(ProjectDrawing.status == "pending").all()
        for d in pending:
            enqueue(d.id)
        if requeue or pending:
            logger.info("[项目预处理] 重启恢复：%d 中断重排，%d 待处理入队",
                        len(requeue), len(pending))
        # 崩溃残留清理：转换中间件 DXF 正常流程用完即删，能活过 2 小时的一定是
        # 处理进程被杀留下的孤儿（2026-09-23 事故曾囤 197 个 × 57MB ≈ 11GB）。
        # 注意只删 mtime 过期的，正在处理的图（持锁）不受影响。
        cutoff = time.time() - 2 * 3600
        swept = 0
        for p in PROJECTS_DIR.glob("*/*.dxf"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    swept += 1
            except OSError:
                pass
        if swept:
            logger.warning("[项目预处理] 清理崩溃残留 DXF %d 个", swept)
    finally:
        db.close()


def _worker_loop():
    while True:
        drawing_id = _task_queue.get()
        try:
            with _preprocess_lock():  # 两 worker 进程共享全机串行，防两张图并行渲染打爆内存
                _run_isolated(drawing_id)
        except Exception:
            logger.exception("[项目预处理] 图纸 %s 处理异常", drawing_id)
        finally:
            _task_queue.task_done()
        # 画像/关系图后处理：锁外执行（LLM 网络调用不占渲染互斥），失败不影响 ready
        try:
            _post_process_drawing(drawing_id)
        except Exception:
            logger.exception("[画像] 后处理异常 drawing=%s", drawing_id)


def _frames_meta(frames: list, masked_info: dict) -> list[dict]:
    """切片图框元数据：rect（世界坐标，与 det["frames"]/切片同序）+ rect 内图签标注提取图名。
    世界坐标经 rect 归属判定即可支撑"按图幅分组文字摘要"，无需渲染变换参数。"""
    from services.drawing_service import _looks_title_block, _TB_TITLE_SUFFIX
    anns = masked_info.get("text_annotations") or []
    out = []
    for i, rect in enumerate(frames, 1):
        x0, y0, x1, y1 = rect
        inside = []
        for a in anns:
            pos = a.get("position")
            t = (a.get("text") or "").strip()
            if not t or not pos:
                continue
            if x0 <= pos[0] <= x1 and y0 <= pos[1] <= y1 and _looks_title_block(t):
                inside.append(t)
        title = ""
        for t in inside:
            if _TB_TITLE_SUFFIX.search(t):
                title = t
                break
        if not title and inside:
            title = inside[0]
        out.append({"frame": f"p{i}", "rect": [round(float(v), 1) for v in rect],
                    "title": title[:60]})
    return out


def _post_process_drawing(drawing_id: int):
    """单图画像 + 批次完成自查触发关系图（worker 主进程侧，锁外）。
    ProfileAgent 输入全走脱敏态（ctx 本就密文；文件名单独过项目对照表）。"""
    import asyncio
    from config import load_config
    cfg = load_config()
    if not cfg.agent_settings.profile_agent_enabled:
        return
    from db.database import SessionLocal
    from db.models.project import ProjectDrawing
    from services.llm_service import LLMService
    from services.agents import profile as profile_agent
    from services.mask_service import (
        load_project_cipher, save_project_cipher, mask_text)

    db = SessionLocal()
    try:
        rec = db.get(ProjectDrawing, drawing_id)
        if not rec or rec.status != "ready" or not rec.cache_file_id:
            return
        pid, fid, filename = rec.project_id, rec.cache_file_id, rec.filename
        busy = db.query(ProjectDrawing).filter(
            ProjectDrawing.project_id == pid,
            ProjectDrawing.status.in_(["pending", "processing"])).count()
    finally:
        db.close()

    ctx_path = UPLOAD_DIR / f"{fid}.json"
    try:
        info = json.loads(ctx_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not info.get("summary"):
        pdir = project_dir(pid)
        cmap = load_project_cipher(pdir)
        masked_name = mask_text(filename, cmap)
        save_project_cipher(pdir, cmap)
        try:
            from config import resolve_provider_index
            res = asyncio.run(profile_agent.summarize_drawing(
                LLMService(), resolve_provider_index(cfg, cfg.profile_provider_index),
                info, masked_name))
        except Exception:
            logger.exception("[画像] 摘要生成失败 drawing=%s", drawing_id)
            res = None
        if res:
            info["summary"] = res["summary"]
            by_frame = {f.get("frame"): f for f in res.get("frame_summaries") or []}
            for i, fr in enumerate(info.get("frames") or [], 1):
                extra = by_frame.get(f"p{i}")
                if extra:
                    if extra.get("title") and not fr.get("title"):
                        fr["title"] = extra["title"]
                    if extra.get("summary"):
                        fr["summary"] = extra["summary"]
            tmp = ctx_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
            os.replace(str(tmp), str(ctx_path))
            logger.info("[画像] 摘要完成 drawing=%s", drawing_id)

    # 批次完成自查：该项目 0 pending/processing → 重建关系图（指纹变化时）
    if busy == 0:
        build_project_relations(pid)


def _project_drawing_cards(pid: int) -> tuple[list[dict], list[int]]:
    """项目全部 ready 图纸的画像卡（脱敏态 summary/filename）+ id 指纹"""
    from db.database import SessionLocal
    from db.models.project import ProjectDrawing
    from services.mask_service import (
        load_project_cipher, save_project_cipher, mask_text)

    db = SessionLocal()
    try:
        drawings = db.query(ProjectDrawing).filter_by(
            project_id=pid, status="ready").order_by(ProjectDrawing.id).all()
        rows = [(d.id, d.cache_file_id, d.filename, d.rel_path) for d in drawings]
    finally:
        db.close()
    pdir = project_dir(pid)
    cmap = load_project_cipher(pdir)
    cards = []
    for did, fid, filename, rel_path in rows:
        summary = ""
        try:
            info = json.loads((UPLOAD_DIR / f"{fid}.json").read_text(encoding="utf-8"))
            summary = info.get("summary") or ""
        except Exception:
            pass
        cards.append({
            "file_id": fid,
            "filename": mask_text(filename, cmap),
            "rel_path": mask_text(rel_path or filename, cmap),
            "summary": summary,
        })
    save_project_cipher(pdir, cmap)
    return cards, sorted(did for did, *_ in rows)


async def abuild_project_relations(pid: int, force: bool = False) -> dict | None:
    """重建项目批次关系图（脱敏态落盘 data/projects/{pid}/relations.json）。
    指纹（ready 图纸 id 排序）不变且非 force → 跳过。失败返回 None。"""
    from config import load_config
    cfg = load_config()
    if not cfg.agent_settings.profile_agent_enabled:
        return None
    cards, fingerprint = _project_drawing_cards(pid)
    if not cards:
        return None
    rel_path = project_dir(pid) / "relations.json"
    if not force and rel_path.exists():
        try:
            old = json.loads(rel_path.read_text(encoding="utf-8"))
            if old.get("drawing_ids") == fingerprint and old.get("description"):
                return old
        except Exception:
            pass
    from services.llm_service import LLMService
    from services.agents import profile as profile_agent
    from config import resolve_provider_index
    res = await profile_agent.build_relations(
        LLMService(), resolve_provider_index(cfg, cfg.profile_provider_index), cards)
    if not res:
        return None
    res["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    res["drawing_ids"] = fingerprint
    tmp = rel_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(rel_path))
    logger.info("[画像] 关系图完成 project=%s 图纸=%d 边=%d",
                pid, len(cards), len(res.get("edges") or []))
    return res


def build_project_relations(pid: int, force: bool = False) -> dict | None:
    """同步包装（worker 线程用；async 上下文请直接 await abuild_project_relations）"""
    import asyncio
    try:
        return asyncio.run(abuild_project_relations(pid, force=force))
    except Exception:
        logger.exception("[画像] 关系图生成失败 project=%s", pid)
        return None


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
            # 多图框两重判定切片（矢量×OCR）：成功则多页化，失败保持单页
            # FRAME_SLICE_ENABLED=False 时整体跳过（最小补丁行为与线上一致）
            if png and FRAME_SLICE_ENABLED:
                try:
                    from services.frame_detect import detect_and_slice
                    det = detect_and_slice(str(dxf_path), png, str(UPLOAD_DIR / fid))
                    if det["slices"]:
                        masked_info["frame_count"] = det["frame_count"]
                        masked_info["image_count"] = 1 + len(det["slices"])  # 首页=整图总览
                        # 图框 rect/图名落盘：定位Agent免OCR快路径 + 按图幅文字摘要归属判定
                        masked_info["frames"] = _frames_meta(det["frames"], masked_info)
                    elif det["ocr_count"]:
                        # 矢量失明但 OCR 有估计：不切片，记录供 AI 上下文
                        masked_info["frame_count"] = det["ocr_count"]
                    masked_info["frame_method"] = det["method"]
                except Exception:
                    logger.exception("[项目预处理] 图框切片失败（保持单页）: %s", rec.filename)

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

        # 6. 清理 DXF 中间文件（用完即删，不占磁盘）
        if suffix == ".dwg":
            dxf_path.unlink(missing_ok=True)
        # 解析中间 JSON 也删（原始解析结果已脱敏落到 drawing_uploads）
        (pdir / f"{fid}.parsed.json").unlink(missing_ok=True)
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
                if name.endswith("/"):
                    continue
                fn = Path(name).name
                if not fn or fn.startswith("."):
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
                # 保留压缩包内目录层级（如 04-暖通/计算书/xxx.dwg）
                parts = name.split("/")
                rel_parts = []
                for p in parts[:-1]:
                    try:
                        p_fixed = p.encode("cp437").decode("gbk")
                    except (UnicodeEncodeError, UnicodeDecodeError):
                        p_fixed = p
                    if p_fixed and not p_fixed.startswith("."):
                        rel_parts.append(p_fixed)
                rel_path = "/".join(rel_parts + [fn_fixed]) if rel_parts else fn_fixed
                dest = pdir / f"orig_{uuid.uuid4().hex[:8]}{suffix}"
                dest.write_bytes(zf.read(name))

                db = SessionLocal()
                try:
                    rec = ProjectDrawing(
                        project_id=project_id, filename=fn_fixed,
                        rel_path=rel_path,
                        file_type=suffix.lstrip("."), status="pending",
                        original_path=str(dest), uploaded_by=uploaded_by,
                    )
                    db.add(rec)
                    db.commit()
                    db.refresh(rec)
                    created.append({"id": rec.id, "filename": fn_fixed, "rel_path": rel_path})
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
