# -*- coding: utf-8 -*-
"""真实图纸（rar 抽取的 dwg/pdf）预处理管线端到端验证"""
import io
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
SRC = Path(r"D:/桌面/小图兔/素材/测试图纸/_extract")


def login(username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


with client:
    admin = login("admin", "admin123")
    pname = f"真实图纸验证{int(time.time()) % 100000}"
    r = client.post("/api/projects", json={"name": pname, "description": "真实rar素材"}, headers=admin)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    print("项目:", pid)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in SRC.iterdir():
            if f.suffix.lower() in (".dwg", ".pdf"):
                zf.write(f, arcname=f.name)
    buf.seek(0)
    r = client.post(f"/api/projects/{pid}/drawings/zip",
                    files={"file": ("real.zip", buf, "application/zip")}, headers=admin)
    assert r.status_code == 200, r.text
    res = r.json()
    print("入库:", [(c["id"], c["filename"]) for c in res["created"]])

    # 轮询（串行 worker，真实文件可能要几分钟）
    t0 = time.time()
    pending = {c["id"] for c in res["created"]}
    while pending and time.time() - t0 < 600:
        r = client.get(f"/api/projects/{pid}/drawings?scope=admin", headers=admin)
        for d in r.json():
            if d["id"] in pending and d["status"] in ("ready", "failed"):
                print(f"  [{d['status']:>7}] {d['filename']}  "
                      f"has_image={d.get('has_image')} error={d.get('error', '')[:120]}")
                pending.discard(d["id"])
        if pending:
            time.sleep(5)
    assert not pending, f"超时未处理完: {pending}"

    # 检查产物目录 + 脱敏产物
    import json
    proj_dir = Path(f"../data/projects/{pid}")
    cmap_files = list(proj_dir.glob("*/masked_text.json"))
    cipher = proj_dir / "cipher_map.json"
    print("脱敏产物:", len(cmap_files), "份 masked_text.json；项目对照表存在:", cipher.exists())
    if cipher.exists():
        data = json.loads(cipher.read_text(encoding="utf-8"))
        print("对照表单位数:", len(data["units"]), "人名数:", len(data["persons"]))
        for k, v in list(data["units"].items())[:8]:
            print("  ", v, "<-", k)
        for k, v in list(data["persons"].items())[:8]:
            print("  ", v, "<-", k)
    print("\n=== 真实图纸管线验证完成 ===")
