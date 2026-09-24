# -*- coding: utf-8 -*-
"""验证 4 项修复：本地起 TestClient，上传真实 DWG+PDF，建图纸集问答。
①文本通道重排 ②图像多页轮转 ③路由目录卡 ④PDF深页路由"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fastapi.testclient import TestClient
from main import app

EXTRACT = r"D:\桌面\小图兔\素材\测试图纸\_extract"
client = TestClient(app)

with client:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    H = {"Authorization": f"Bearer {r.json()['access_token']}"}

    fids = {}
    for fn in ["3数据中心结构图 C12独立基础.dwg", "01-云中心设计说明-总说明-260630.pdf"]:
        with open(Path(EXTRACT) / fn, "rb") as f:
            r = client.post("/api/drawing/upload", files={"file": (fn, f)}, headers=H)
        assert r.status_code == 200, r.text
        fids[fn] = r.json()["file_id"]
        print("上传:", fn, "->", fids[fn], "image_count=", r.json().get("image_count"))

    r = client.post("/api/drawing/sets", json={"file_ids": list(fids.values())}, headers=H)
    assert r.status_code == 200, r.text
    set_id = r.json()["set_id"]
    print("set:", set_id)
    for s in r.json()["sheets"]:
        print("  目录卡:", s["filename"][:24], "=>", s["summary"][:100])

    # DWG 问题：答案在文字标注里（文本通道）
    r = client.post("/api/drawing/chat", json={
        "set_id": set_id, "question": "C12独立基础这张图的图纸内容是什么？基础相关的标注有哪些？"}, headers=H)
    assert r.status_code == 200, r.text
    a = r.json()["answer"]
    print("DWG问答:", a[:200].replace("\n", " "))
    assert r.json()["with_image"]

    # PDF 深页路由：问一个首页没有、深页才有的内容
    r = client.post("/api/drawing/chat", json={
        "set_id": set_id, "question": "这份设计说明里关于绿色建筑或节能的章节说了什么？"}, headers=H)
    assert r.status_code == 200, r.text
    print("PDF问答:", r.json()["answer"][:200].replace("\n", " "))

    # 检查 PDF 是否缓存了 page_texts、是否补渲了深页
    ctx = json.loads((Path("data/drawing_uploads") / f"{fids['01-云中心设计说明-总说明-260630.pdf']}.json").read_text(encoding="utf-8"))
    pts = ctx.get("page_texts")
    print("page_texts 缓存:", None if pts is None else len(pts), "页, total=", ctx.get("page_total"))
    import glob
    deep = glob.glob(str(Path("data/drawing_uploads") / f"{fids['01-云中心设计说明-总说明-260630.pdf']}_p*.png"))
    print("PDF 渲染页:", sorted(Path(p).name for p in deep))
    print("=== 4 项修复本地验证完成 ===")
