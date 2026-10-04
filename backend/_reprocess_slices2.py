# -*- coding: utf-8 -*-
"""逐帧高分辨率切片重跑（一次性脚本，跑完即删）。

v2 与 v1 差异：强制重切全部 DWG/DXF（不清 ctx 的 image_count 判断），
因为渲染器已从"共享画布裁剪"换成"逐帧独立渲染"（切片分辨率 1088→4096）。
ctx 只改数值字段（image_count/frame_count/frame_method），不动文本/脱敏。

输入（_reprocess2 目录）：
  manifest.json / src/opt/xiaotutu/data/...（原件、ctx、总览）
输出：
  out/{fid}_pN.png 切片、out/{fid}.json 补丁ctx、report.json
用法: cd backend && PYTHONIOENCODING=utf-8 python _reprocess_slices2.py
"""
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from services.drawing_service import convert_dwg_to_dxf  # noqa: E402
from services.frame_detect import detect_and_slice  # noqa: E402

logging.basicConfig(level=logging.WARNING)

WORK = Path(r"D:\桌面\小图兔\素材\测试图纸\_reprocess2")
SRC = WORK / "src" / "opt" / "xiaotutu" / "data"
OUT = WORK / "out"
TMP = WORK / "tmp_dxf"
OUT.mkdir(exist_ok=True)
TMP.mkdir(exist_ok=True)

rows = json.load(open(WORK / "manifest.json", encoding="utf-8-sig"))
dwg = [r for r in rows if (r["original_path"] or "").lower().endswith((".dwg", ".dxf"))]

report = []
for i, r in enumerate(dwg, 1):
    fid = r["cache_file_id"]
    name = r["filename"]
    ctx_path = SRC / "drawing_uploads" / f"{fid}.json"
    png_path = SRC / "drawing_uploads" / f"{fid}.png"
    orig = WORK / "src" / r["original_path"].replace("/app/", "opt/xiaotutu/", 1).lstrip("/")

    rec = {"id": r["id"], "fid": fid, "filename": name}
    t0 = time.time()
    try:
        # 完成标记 = 补丁 ctx（最后写入）。只有切片没有 json = 半成品（被杀残留），
        # 清掉切片重跑，避免缺页/脏文件被当成已完成。
        if not (OUT / f"{fid}.json").exists():
            for stale in OUT.glob(f"{fid}_p*.png"):
                stale.unlink()
        else:
            rec.update(skip="已处理(断点续跑)")
            report.append(rec)
            print(f"[{i}/{len(dwg)}] id={r['id']} 跳过-已处理  {name[:30]}", flush=True)
            json.dump(report, open(WORK / "report.json", "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            continue
        if not ctx_path.exists() or not orig.exists():
            rec.update(skip="缺文件"); report.append(rec); continue
        ctx = json.load(open(ctx_path, encoding="utf-8"))
        old_ic = ctx.get("image_count", 1)

        if str(orig).lower().endswith(".dwg"):
            dxf = TMP / f"{fid}.dxf"
            ok, msg = convert_dwg_to_dxf(str(orig), str(dxf))
            if not ok:
                rec.update(error=f"dwg2dxf: {msg}"); report.append(rec); continue
        else:
            dxf = orig

        det = detect_and_slice(str(dxf), str(png_path), str(OUT / fid))
        rec.update(method=det["method"], slices=len(det["slices"]), old_ic=old_ic)

        if det["slices"]:
            ctx["image_count"] = 1 + len(det["slices"])
            ctx["frame_count"] = det["frame_count"]
            ctx["frame_method"] = det["method"]
            json.dump(ctx, open(OUT / f"{fid}.json", "w", encoding="utf-8"),
                      ensure_ascii=False)
        elif det.get("ocr_count"):
            ctx["frame_count"] = det["ocr_count"]
            ctx["frame_method"] = det["method"]
            json.dump(ctx, open(OUT / f"{fid}.json", "w", encoding="utf-8"),
                      ensure_ascii=False)
    except Exception as e:
        rec.update(error=f"{type(e).__name__}: {e}")
    rec["sec"] = round(time.time() - t0, 1)
    report.append(rec)
    print(f"[{i}/{len(dwg)}] id={r['id']} {rec.get('skip') or rec.get('error') or (str(rec.get('slices'))+'片 '+str(rec.get('method')))} {rec['sec']}s  {name[:30]}",
          flush=True)
    json.dump(report, open(WORK / "report.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

done = [x for x in report if x.get("slices")]
print(f"\n完成：{len(done)} 张出切片 / 共 {len(dwg)} 张 DWG/DXF")
