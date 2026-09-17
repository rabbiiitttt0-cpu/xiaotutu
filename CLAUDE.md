# 小图兔 — 图纸识别助手（项目开发指南）

> 独立的工程图纸识别助手网站：从「同舟智航施工方案管理系统」裁剪识图模块而来。
> 保留完整识图功能，删除方案编写/审查/质量/知识库等无关功能。
> 📛 品牌：小图兔。开发者邮箱：1055872751@qq.com。

> 📋 **跨会话状态板**：`进度.md`（本地维护，每会话结束更新）。新会话先读本文件 + `进度.md` + `git log`。

---

## 一、技术栈

FastAPI + Vue3 + Element Plus（PC 前端）+ Vant（移动 H5 前端）。
数据库：本地 SQLite（开发）/ 独立 PostgreSQL（生产）。
LLM：多模态视觉模型（DeepSeek-V4.1-Flash 等，Provider 体系）。
解析：ezdxf（DXF）+ LibreDWG（DWG→DXF）+ PyMuPDF（PDF）+ RapidOCR（扫描件补文字层）。

## 二、目录结构

```
小图兔/
├── CLAUDE.md              # 本文件
├── 进度.md                # 状态板
├── backend/               # FastAPI 后端
│   ├── main.py            # 入口
│   ├── config.py          # AppConfig：LLM Provider + 识图设置
│   ├── auth/              # 认证：登录/注册/JWT（简化，无三级权限）
│   ├── api/drawing.py     # 识图 API
│   ├── services/          # drawing_service / llm_service / audit_log
│   ├── db/                # SQLAlchemy（users + 日志表）
│   └── requirements.txt
├── frontend-pc/           # PC 前端（Element Plus）
├── frontend-mobile/       # 移动 H5 前端（Vant）
├── assets/                # CJK 字体 + LibreDWG 二进制
└── deploy/                # Docker + 部署脚本
```

## 三、核心功能（识图模块，完整保留）

- 上传：DXF（直传）/ DWG（LibreDWG 转 DXF）/ PDF（矢量直渲 + 文字层提取）
- 视觉问答：文本摘要 + 渲染图双通道送多模态模型
- 图纸集：一套多图 + 图幅级路由问答（>3 张自动选图）
- 材料提取 / 快速交底
- 截图提问（框选局部）/ 语音输入
- 预览：PNG/SVG 双轨、缩放拖动、图幅切换、拖拽分隔条
- 识图精度：文字标注去重注入、图框内容判定、OCR 补文字层、密集小字分块渲染、DXF 块展开
- 日志：操作审计 + LLM 调用 + 错误日志（仅超管）
- 用量统计（仅超管）

## 四、用户体系（简化）

- 注册（审批制：注册后 is_active=False，超管启用）
- 登录（JWT：access 120min + refresh 3天）
- 超管：管理用户（启用/禁用/删除）、看日志、看用量
- 无三级权限、无 AdminGrant、无 scope 四维度、无功能模块 6 开关

## 五、双前端架构

- `frontend-pc/`：PC 桌面布局
- `frontend-mobile/`：移动 H5（Vant）
- 两套前端共享同一后端（数据天然互通）
- 登录页「PC版 / 手机版」一键切换（跳转对方前端，token 经 localStorage 共享）

## 六、常用命令

```bash
# 后端（进入 backend 目录）
python -m uvicorn main:app --host 127.0.0.1 --port 7780 --reload
# PC 前端
cd frontend-pc && npm install && npm run dev   # / npm run build
# 移动前端
cd frontend-mobile && npm install && npm run dev
```

端口：后端 7780 / PC 前端 5173 / 移动前端 5174。

## 七、开发约定

1. 后端跑脚本：`PYTHONIOENCODING=utf-8`（Windows GBK 不支持 emoji）
2. LLM 统一走 `LLMService.chat_complete()`
3. 存储：图纸/会话/配置 JSON 落盘 `data/`；用户/日志 SQLAlchemy
4. 下载/预览一律 axios+token 或后端鉴权路由，禁 window.open 裸开 URL
5. 改前端必须 rebuild + Playwright 真浏览器验证
6. commit 可直接做，push 到 GitHub 前先问

## 八、踩坑记录（迁移自同舟智航，勿回退）

1. 嵌入式 Python 3.12（rapidocr 不兼容 3.14）
2. OMML 公式提取走 `para_full_text()`（para.text 丢 m:t）
3. DWG 转换：LibreDWG 优先（仓库内置），ODA 装了自动优先
4. 密集小字判定：OCR 文本框 ≥100 且中位框高 ≤40px → 分块渲染
5. deploy 脚本不更新已存在的 IMAGE_TAG（部署前先 sed）
6. 前端改动不生效先怀疑浏览器缓存（强刷 Ctrl+Shift+R）
