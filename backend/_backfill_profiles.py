# -*- coding: utf-8 -*-
"""存量图纸画像回填（一次性脚本，跑完即删）。

服务器容器内运行：docker exec xiaotutu python /app/backend/_backfill_profiles.py
（也可先跑单个项目：... _backfill_profiles.py 3）

对每张 ready 图纸：
1. frames 标题回填：切片右下角 40%×28% 区域 OCR → 图签匹配（_looks_title_block），
   标题经项目对照表脱敏后写入 ctx frames[].title（ctx 文字层全密文的红线不变）；
2. summary：ProfileAgent.summarize_drawing（输入全脱敏态）；
每个项目完成后：build_project_relations（指纹含 summary 状态，自动重建）。

断点续跑：已写 summary 的图纸跳过；Ctrl-C 后再跑继续。
"""
import asyncio
import io
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import DATA_DIR, load_config  # noqa: E402
from services import project_service  # noqa: E402
from services.drawing_service import (  # noqa: E402
    _get_ocr_engine, _looks_title_block, _TB_TITLE_SUFFIX)
from services.mask_service import (  # noqa: E402
    load_project_cipher, save_project_cipher, mask_text)

UPLOAD_DIR = DATA_DIR / "drawing_uploads"


def slice_title_ocr(png_path: Path) -> str:
    """切片右下角图签区 OCR → 图名（原文，调用方负责脱敏）"""
    from PIL import Image
    im = Image.open(png_path)
    w, h = im.size
    crop = im.crop((int(w * 0.6), int(h * 0.72), w, h))
    im.close()
    buf = io.BytesIO()
    crop.save(buf, "PNG")
    tmp = png_path.parent / f".{png_path.stem}_tb.png"
    try:
        tmp.write_bytes(buf.getvalue())
        result, _ = _get_ocr_engine()(str(tmp))
    finally:
        tmp.unlink(missing_ok=True)
    texts = [t for _, t, s in (result or []) if s > 0.5]
    titled = [t.strip() for t in texts if _looks_title_block(t.strip())]
    for t in titled:
        if _TB_TITLE_SUFFIX.search(t):
            return t
    return titled[0] if titled else ""


def backfill_project(pid: int) -> dict:
    from db.database import SessionLocal
    from db.models.project import ProjectDrawing
    from services.llm_service import LLMService
    from services.agents import profile as profile_agent

    cfg = load_config()
    llm = LLMService()
    pidx = cfg.drawing_provider_index
    pdir = project_service.project_dir(pid)

    db = SessionLocal()
    try:
        rows = [(d.id, d.cache_file_id, d.filename)
                for d in db.query(ProjectDrawing).filter_by(
                    project_id=pid, status="ready").order_by(ProjectDrawing.id)]
    finally:
        db.close()

    cmap = load_project_cipher(pdir)
    stats = {"summarized": 0, "titled": 0, "skipped": 0, "failed": 0}
    for did, fid, filename in rows:
        ctx_path = UPLOAD_DIR / f"{fid}.json"
        try:
            info = json.loads(ctx_path.read_text(encoding="utf-8"))
        except Exception:
            stats["failed"] += 1
            continue
        changed = False

        # 1. 图幅标题回填（无 frames 且有切片时）
        if "frames" not in info:
            import re as _re
            pat = _re.compile(rf"^{_re.escape(fid)}_p(\d+)$")
            slices = sorted(
                (p for p in UPLOAD_DIR.glob(f"{fid}_p*.png") if pat.match(p.stem)),
                key=lambda p: int(pat.match(p.stem).group(1)))
            if slices:
                frames = []
                for i, p in enumerate(slices, 1):
                    try:
                        raw_title = slice_title_ocr(p)
                    except Exception:
                        raw_title = ""
                    title = mask_text(raw_title, cmap) if raw_title else ""
                    frames.append({"frame": f"p{i}", "title": title[:60]})
                    if title:
                        stats["titled"] += 1
                info["frames"] = frames
                changed = True

        # 2. 内容摘要
        if not info.get("summary"):
            masked_name = mask_text(filename, cmap)
            try:
                res = asyncio.run(profile_agent.summarize_drawing(
                    llm, pidx, info, masked_name))
            except Exception:
                res = None
            if res:
                info["summary"] = res["summary"]
                by_frame = {f.get("frame"): f
                            for f in res.get("frame_summaries") or []}
                for i, fr in enumerate(info.get("frames") or [], 1):
                    extra = by_frame.get(f"p{i}")
                    if extra:
                        if extra.get("title") and not fr.get("title"):
                            fr["title"] = extra["title"]
                        if extra.get("summary"):
                            fr["summary"] = extra["summary"]
                stats["summarized"] += 1
                changed = True
        if changed:
            tmp = ctx_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
            os.replace(str(tmp), str(ctx_path))
            save_project_cipher(pdir, cmap)
            print(f"  [回填] drawing={did} {filename[:30]} "
                  f"summary={'有' if info.get('summary') else '无'} "
                  f"frames={len(info.get('frames') or [])}", flush=True)
        else:
            stats["skipped"] += 1

    # 3. 批次关系图
    project_service.build_project_relations(pid, force=True)
    return stats


def main():
    from db.database import SessionLocal
    from db.models.project import Project
    only = int(sys.argv[1]) if len(sys.argv) > 1 else None
    db = SessionLocal()
    try:
        q = db.query(Project).filter_by(is_active=True)
        pids = [p.id for p in q.all()]
    finally:
        db.close()
    if only:
        pids = [p for p in pids if p == only]
    t0 = time.time()
    for pid in pids:
        print(f"[项目 {pid}] 开始回填", flush=True)
        try:
            stats = backfill_project(pid)
            print(f"[项目 {pid}] 完成 {stats}", flush=True)
        except Exception as e:
            print(f"[项目 {pid}] 失败: {e}", flush=True)
    print(f"全部完成，耗时 {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
