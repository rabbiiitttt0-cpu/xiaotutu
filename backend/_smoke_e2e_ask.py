# -*- coding: utf-8 -*-
"""端到端问答：项目图纸（脱敏输入 → 还原输出 → 5天会话落库）"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def login(u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


with client:
    admin = login("admin", "admin123")
    # 找「真实图纸验证」最新项目里的 ready 图纸
    ps = client.get("/api/projects", headers=admin).json()
    proj = [p for p in ps if "真实图纸验证" in p["name"]][-1]
    pid = proj["id"]
    # admin 是成员（上个脚本已加）
    drawings = client.get(f"/api/projects/{pid}/drawings?scope=all", headers=admin).json()
    ready = [d for d in drawings if d["status"] == "ready"]
    assert ready, "无 ready 图纸"
    did = ready[0]["id"]
    print("选用图纸:", ready[0]["filename"])

    # 项目问答：先建临时图纸集，再带 set_id 走 /chat（脱敏 + 会话）
    r = client.post("/api/drawing/project_set",
                    json={"project_id": pid, "drawing_ids": [did]}, headers=admin)
    assert r.status_code == 200, r.text
    set_id = r.json()["set_id"]
    r = client.post("/api/drawing/chat", json={
        "set_id": set_id,
        "project_id": pid,
        "drawing_ids": [did],
        "question": "这张图纸里出现的建设单位是哪家？请原样引用文字。",
    }, headers=admin)
    assert r.status_code == 200, r.text
    data = r.json()
    print("session_id:", data.get("session_id"))
    answer = data.get("answer", "")
    print("answer 前200字:", answer[:200].replace("\n", " "))

    # 5 天会话：应能列出并恢复
    r = client.get(f"/api/projects/{pid}/sessions", headers=admin)
    sessions = r.json()
    assert sessions, "会话未落库"
    sid = sessions[0]["id"]
    r = client.get(f"/api/projects/{pid}/sessions/{sid}", headers=admin)
    assert r.status_code == 200
    sess = r.json()
    print("会话恢复: title=", sess.get("title"), " messages=", len(sess.get("messages", [])),
          " expires_at=", sess.get("expires_at"))
    print("\n=== 端到端问答 + 会话恢复 OK ===")
