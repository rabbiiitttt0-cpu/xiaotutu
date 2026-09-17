# -*- coding: utf-8 -*-
"""项目图纸管理端到端冒烟测试（本地 SQLite + TestClient）"""
import io
import json
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def login(username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


with client:  # lifespan: init_db + worker + cleaner
    admin = login("admin", "admin123")

    # 1. 建项目
    pname = f"测试项目{int(time.time()) % 100000}"
    r = client.post("/api/projects", json={"name": pname, "description": "冒烟"}, headers=admin)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    print("1. 项目创建 OK, id =", pid)

    # 2. 建普通用户并加为成员
    uname = f"member_{int(time.time()) % 100000}"
    r = client.post("/api/auth/admin/users",
                    json={"username": uname, "password": "test1234", "display_name": "测试成员"},
                    headers=admin)
    assert r.status_code == 200, r.text
    uid = r.json().get("id") or r.json().get("user", {}).get("id")
    if not uid:
        users = client.get("/api/auth/admin/users", headers=admin).json()
        uid = [u for u in (users if isinstance(users, list) else users.get("items", users.get("users", [])))
               if u["username"] == uname][0]["id"]
    r = client.post(f"/api/projects/{pid}/members", json={"user_id": uid}, headers=admin)
    assert r.status_code == 200, r.text
    print("2. 成员添加 OK, uid =", uid)

    # 3. zip 上传（含 dxf + 不支持文件）
    dxf_src = Path("../data/_test.dxf")
    assert dxf_src.exists(), "缺测试 dxf"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("图纸/桩基布置图.dxf", dxf_src.read_bytes())
        zf.writestr("说明.txt", "not a drawing")
    buf.seek(0)
    r = client.post(f"/api/projects/{pid}/drawings/zip",
                    files={"file": ("drawings.zip", buf, "application/zip")}, headers=admin)
    assert r.status_code == 200, r.text
    res = r.json()
    print("3. zip 入库 OK:", res)
    assert len(res["created"]) == 1 and res["skipped"] == ["说明.txt"]

    # 4. 轮询处理状态（串行 worker）
    did = res["created"][0]["id"]
    for i in range(120):
        r = client.get(f"/api/projects/{pid}/drawings?scope=admin", headers=admin)
        d = [x for x in r.json() if x["id"] == did][0]
        if d["status"] in ("ready", "failed"):
            break
        time.sleep(1)
    print("4. 预处理状态:", d["status"], d.get("error", ""), "has_image:", d["has_image"])
    assert d["status"] == "ready", d.get("error")

    # 5. 常用标记
    r = client.patch(f"/api/projects/{pid}/drawings/{did}", json={"is_frequent": True}, headers=admin)
    assert r.status_code == 200

    # 6. 成员视角：mine / frequent 列表 / info（还原）
    member = login(uname, "test1234")
    r = client.get("/api/projects/mine", headers=member)
    assert any(p["id"] == pid for p in r.json()), r.text
    r = client.get(f"/api/projects/{pid}/drawings?scope=frequent", headers=member)
    assert len(r.json()) == 1 and r.json()[0]["is_frequent"]
    cache_fid = r.json()[0]["cache_file_id"]
    r = client.get(f"/api/projects/{pid}/drawings/{did}/info", headers=member)
    assert r.status_code == 200, r.text
    print("6. 成员视角 OK, cache_file_id =", cache_fid, "desc 前40字:", r.json()["description"][:40])

    # 7. 非成员 403
    uname2 = f"outsider_{int(time.time()) % 100000}"
    client.post("/api/auth/admin/users",
                json={"username": uname2, "password": "test1234"}, headers=admin)
    outsider = login(uname2, "test1234")
    r = client.get(f"/api/projects/{pid}/drawings", headers=outsider)
    assert r.status_code == 403, r.status_code
    r = client.get("/api/projects", headers=outsider)  # 非超管访问管理接口
    assert r.status_code == 403, r.status_code
    print("7. 权限拦截 OK")

    # 8. 图纸集（成员可建）
    r = client.post(f"/api/projects/{pid}/sets",
                    json={"name": "桩基一套", "drawing_ids": [did]}, headers=member)
    assert r.status_code == 200, r.text
    sid_set = r.json()["id"]
    r = client.get(f"/api/projects/{pid}/sets", headers=member)
    assert r.json()[0]["name"] == "桩基一套"
    print("8. 图纸集 OK, id =", sid_set)

    # 9. project_set（问答用临时集）
    r = client.post("/api/drawing/project_set",
                    json={"project_id": pid, "drawing_ids": [did]}, headers=member)
    assert r.status_code == 200, r.text
    pset = r.json()
    print("9. project_set OK:", pset["set_id"], "sheets:", len(pset["sheets"]))

    # 10. 预览图（经 drawing image 端点）
    r = client.get(f"/api/drawing/{cache_fid}/image", headers=member)
    print("10. 预览图:", r.status_code, r.headers.get("content-type"))

    # 11. 会话列表（空）+ 清理函数
    r = client.get(f"/api/projects/{pid}/sessions", headers=member)
    assert r.json() == []
    from services.project_service import cleanup_expired_sessions
    cleanup_expired_sessions()
    print("11. 会话接口 OK")

    print("\n=== 全部通过 ===")
