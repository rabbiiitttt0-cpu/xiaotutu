# 看图兔 · 项目图纸管理 + 预处理 + 脱敏 + 5天会话 设计文档

日期：2026-09-17
状态：待评审

## 1. 背景与目标

当前识图流程是**实时解析**：用户上传 DWG → LibreDWG 转 DXF → ezdxf 解析 → matplotlib 渲染 → 才进入问答。在 2C4G 生产机上：

- DWG→DXF 转换 + 大 SVG 渲染单文件耗时 30~60s；
- 多文件并行上传互相抢 CPU，整体更慢且偶发解析失败。

同时，图纸中的**单位名称、人名等敏感信息**目前原样送给云端 LLM，需要脱敏。

### 目标

1. **预处理消除实时解析**：管理员按项目批量上传图纸压缩包，后台异步完成转换/解析/渲染/脱敏，用户问答时直接调取产物，问答延迟 ≈ 纯 LLM 调用时间。
2. **项目图纸管理**：总管理员建项目、传图纸、标记近期常用、管理成员；一个用户可属多个项目。
3. **图纸选用**：问答页除本地上传外，可直接选项目已处理图纸（多张）；常用置顶、可切全部；支持命名「图纸集」。
4. **会话保留 5 天**：会话整体（所选图纸 + 对话 + 上下文）保留，5 天内自动恢复，过期清除。
5. **文本层脱敏**：解析出的文字中的单位名/人名替换为密文（【单位1】/【人名1】），LLM 只见密文，输出给用户前按对照表还原。预处理与实时上传两条路径都生效。

### 非目标（本期不做）

- 图像层脱敏（渲染 PNG 中的敏感文字打码）——先文字层，图像后续再议。
- 图纸版本管理、图纸在线编辑。
- 项目级计费/配额。

## 2. 总体架构

```
管理员                    后台预处理 worker                    普通用户
  │ 上传 zip                │                                  │
  ▼                        ▼                                  ▼
项目图纸库(DB) ──► 串行任务队列 ──► 产物落盘 data/projects/ ──► 问答页选用图纸
                                   (dxf / 解析json / png /      │ 加载脱敏后文字层 + 原图
                                    密文对照表)                  ▼
                                                          LLM(只见密文文字)
                                                                   │
                                                          输出前按对照表还原 ◄── 用户看到真实名称
```

关键决策：**复用现有解析管线**（`drawing_service.py` 的 `convert_dwg_to_dxf` / `parse_dxf` / `render_dxf_png` / `parse_pdf_drawing`），预处理只是「提前调用同一套函数并把产物落盘」，不新写解析逻辑。

## 3. 数据模型

新表（SQLAlchemy，PG/SQLite 通用）：

### projects 项目
| 字段 | 类型 | 说明 |
|---|---|---|
| id | int PK | |
| name | str | 项目名（唯一） |
| description | str | 备注 |
| created_by | int FK users | 创建人（超管） |
| created_at / is_active | | 停用的项目不出现在用户侧 |

### project_members 项目成员（多对多）
| 字段 | 说明 |
|---|---|
| project_id / user_id | 联合唯一 |
| created_at | |

一个用户可属多个项目；一个项目多个成员。成员 = 可选用该项目图纸 + 在该项目下有 5 天会话。

### project_drawings 项目图纸
| 字段 | 说明 |
|---|---|
| id PK | |
| project_id FK | |
| filename | 原始文件名 |
| file_type | dwg / dxf / pdf |
| status | pending / processing / ready / failed |
| error | 失败原因（展示给管理员） |
| is_frequent | bool，管理员标记「近期常用」 |
| original_path | 原始文件落盘路径 |
| artifact_dir | 产物目录 `data/projects/{pid}/{did}/` |
| page_count / meta | 解析摘要（图幅数等） |
| uploaded_by / created_at / processed_at | |

### project_drawing_sets 图纸集
| 字段 | 说明 |
|---|---|
| id / project_id / name | 项目内命名，项目内共享 |
| created_by | 创建成员 |
| created_at | |

### project_drawing_set_items
`set_id + drawing_id`（联合唯一，有序号 sort_order）。

### project_sessions 项目会话（5 天保留）
| 字段 | 说明 |
|---|---|
| id / project_id / user_id | 会话归属用户 |
| title | 首条消息自动生成 |
| drawing_ids | JSON 数组，本会话选用的图纸 |
| messages | JSON 数组 [{role, content, ts}]（含完整上下文） |
| created_at / updated_at | |
| expires_at | = 最后一次活跃 + 5 天，每次追加消息时刷新 |

**清理**：过期会话（expires_at < now）由定时清理删除（启动时 + 每 6 小时一次）。

## 4. 预处理流水线

### 4.1 上传入口（仅超管）

`POST /api/projects/{id}/drawings/zip`：上传 zip → 解压到临时目录 → 对每个支持的文件（.dwg/.dxf/.pdf）建 `project_drawings` 记录（status=pending）→ 入内存任务队列 → 立即返回任务清单。不支持的文件类型跳过并在响应中列出。

### 4.2 后台 worker

- **单线程串行**处理（2C4G 不能并行抢 CPU，与现有实时上传共用机器）。
- 每个文件的处理步骤（全部复用现有函数）：
  1. DWG → `convert_dwg_to_dxf()` → DXF 存产物目录；DXF 直接拷入。
  2. `parse_dxf()` / `parse_pdf_drawing()` → 解析结果 JSON 落盘。
  3. **脱敏**（见 §5）：对解析出的文字层生成密文版 + 对照表，落盘 `masked_text.json` + `cipher_map.json`。
  4. 渲染预览：`render_dxf_png()`（PNG + SVG）/ PDF 页渲染 → PNG 存产物目录。
  5. 状态 → ready；任一步异常 → status=failed + error 信息，继续下一个文件。
- **重启恢复**：应用启动时将 status=processing 的记录重置为 failed（error="服务重启中断"），pending 的重新入队。
- **进度**：前端轮询 `GET /api/projects/{id}/drawings`（含 status/error），无需 WebSocket。

### 4.3 产物目录结构

```
data/projects/{project_id}/{drawing_id}/
├── original.dwg            # 原始文件
├── converted.dxf           # 转换后 DXF
├── parsed.json             # 解析结果（原始，含敏感信息，仅服务端内部用）
├── masked_text.json        # 脱敏后文字层（送 LLM 用）
├── cipher_map.json         # 密文对照表（还原用，绝不出服务端）
├── preview.png / .svg      # 渲染预览（原图，未打码，见 §5.4）
└── meta.json               # 页数/图幅等摘要
```

## 5. 脱敏子系统

### 5.1 识别规则（`backend/services/mask_service.py`）

对解析文字层逐条文本做两类替换：

**单位名**：正则匹配以敏感后缀结尾的连续文本：
`建设|施工|设计|监理|勘察` 单位——如「XX市第三建筑工程有限公司」「XX建筑设计研究院」。匹配模式：紧跟在单位类别标签（建设单位/施工单位/设计单位/监理单位/勘察单位，可带冒号）后的一整段非空白文本，以及正文中以 `公司|研究院|设计院|集团|局` 结尾的实体。

**人名**：标签驱动——在 `制图|设计|校对|审核|审定|项目负责人|专业负责人|复核`（可带冒号）之后出现的 2~4 个连续汉字判为人名。白名单排除常见误命中词（如「设计说明」中的「设计」后跟的不是人名——用「标签后紧邻 + 长度约束 + 不在常用词表」三重约束控制误报）。

### 5.2 密文与对照表

- 每个图纸一份对照表：`【单位1】→ 真实单位名`，`【人名1】→ 真实人名`，编号按出现顺序。
- **同一项目内对照表合并**：同一单位/人名在项目所有图纸中使用同一密文（项目级 `cipher_map.json` + 图纸级增量），保证跨图纸问答时上下文一致。项目级对照表落盘 `data/projects/{pid}/cipher_map.json`。
- 替换发生在**解析结果落盘时**，生成 `masked_text.json`；原始 `parsed.json` 保留在服务端（预览、还原都用它）。

### 5.3 问答链路

```
masked_text.json ──┐
                   ├─► LLM 输入（文字层为密文；预览图本期仍为原图）
预览 PNG ─────────┘
LLM 输出 ──► restore(): 把输出中的【单位N】/【人名N】替换回真实名称 ──► 用户
```

- 还原用**最长匹配优先**的字符串替换，避免 【单位1】/【单位10】前缀冲突。
- LLM 输出中若出现未登记的密文样式，原样保留（不臆造还原）。

### 5.4 边界与说明（写入用户可见的文档注释）

- 本期只脱敏**文字层**；送 LLM 的渲染图仍可能含敏感文字（图像打码后续做）。
- 对照表只存服务端 `data/projects/`，任何 API 不返回。
- **实时上传路径同样生效**：用户本地上传图纸时，解析后过同一 `mask_service`，对照表随会话存内存/会话目录，输出前还原。实时路径的慢问题不变（仍建议用预处理路径），但数据安全口径一致。

## 6. API 设计

### 6.1 项目管理（超管）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/projects | 项目列表（含图纸数/成员数） |
| POST | /api/projects | 新建 {name, description} |
| PUT | /api/projects/{id} | 改名/停用 |
| DELETE | /api/projects/{id} | 删除（连带产物目录、成员、会话） |
| GET/POST/DELETE | /api/projects/{id}/members[/{uid}] | 成员管理 |

### 6.2 图纸管理（超管）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/projects/{id}/drawings/zip | 上传压缩包，返回任务清单 |
| GET | /api/projects/{id}/drawings | 列表（status/error/is_frequent，前端轮询进度） |
| PATCH | /api/projects/{id}/drawings/{did} | 标记/取消常用、重命名 |
| DELETE | /api/projects/{id}/drawings/{did} | 删除图纸及产物 |

### 6.3 用户侧（项目成员）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/projects/mine | 我参与的项目 |
| GET | /api/projects/{id}/drawings?frequent=1|all | 常用（默认）/全部，含图纸集列表 |
| GET | /api/projects/{id}/drawings/{did}/preview | 预览图（原图，成员可见——脱敏只对 LLM） |
| CRUD | /api/projects/{id}/sets[/{sid}] | 图纸集：成员可建，项目共享 |
| GET | /api/projects/{id}/sessions | 我在该项目 5 天内的会话 |
| POST | /api/projects/{id}/sessions | 新建 {drawing_ids 或 set_id} |
| GET/POST | /api/projects/{id}/sessions/{sid}[/messages] | 恢复 / 追加消息（刷新 expires_at） |

### 6.4 问答
现有 `POST /api/drawing/ask` 扩展入参：`project_id + drawing_ids[]` 与本地 `file` 二选一（也允许混用：项目图纸 + 临时补传）。走项目图纸时：

1. 校验用户是项目成员、图纸 status=ready；
2. 直接读产物目录：masked_text.json 作文字层、preview.png 作视觉输入——**零解析耗时**；
3. 输出经 restore 后返回，同时落 project_sessions.messages。

## 7. 前端设计

### 7.1 PC 端

**新增「项目管理」页（超管侧边栏）**：
- 项目列表卡片：名称、图纸数（ready/total）、成员数、状态；新建/编辑/删除。
- 项目详情：① 图纸 tab——zip 上传按钮 + 进度表（文件名/状态/失败原因/常用开关）；② 成员 tab——添加/移除成员（从用户列表选）。

**识图助手页改造**：
- 图纸来源分段控件：`本地上传 | 项目图纸`。
- 项目图纸模式：项目下拉（我参与的）→ 图纸多选列表，**默认只显示「近期常用」图纸和图纸集（置顶），「全部」开关切换看所有 ready 图纸**；图纸集可一键整组选中；选中后可直接「存为图纸集」（命名）。
- 会话侧栏：当前项目的 5 天内会话列表，点击恢复（图纸选择 + 对话上下文一起还原）；显示「保留至 X 月 X 日」。

### 7.2 移动端

本期做最小集：项目图纸选择（常用置顶 + 全部切换、图纸集）+ 5 天会话恢复。项目管理功能仅 PC 端。

## 8. 会话保留与清理

- `expires_at = last_active + 5 天`，每次追加消息/恢复会话时刷新。
- 清理时机：应用启动时扫一次 + 后台每 6 小时扫一次，删除 expires_at < now 的会话（只删 DB 记录，图纸产物不受影响）。
- 恢复语义：5 天内重新进入即看到原对话与所选图纸，可继续提问，上下文（messages 全量）继续送 LLM。

## 9. 错误处理

| 场景 | 行为 |
|---|---|
| zip 中个别文件解析失败 | 该文件 status=failed + error，其余继续；管理员可删除失败记录重传 |
| 处理中服务重启 | 启动时 processing→failed(中断)，pending 重新入队 |
| 选用 failed 图纸问答 | 前端置灰不可选；API 侧 400 |
| 非成员访问项目接口 | 403 |
| 会话过期后访问 | 404 + 前端提示「会话已过期清除」 |
| 脱敏误替换 | 对照表保证可还原；误报只影响送 LLM 的文字，不影响预览与原文件 |

## 10. 性能预期

- 预处理路径问答：省掉转换+解析+渲染（30~60s/文件），请求耗时 ≈ LLM 往返。
- 预处理本身串行执行，对在线问答的影响 ≤ 现在一次实时上传。
- 40G 磁盘：按单图纸产物 ~5MB（dxf+png+json）估算，千级图纸无压力；删除项目/图纸时清目录。

## 11. 测试要点

1. mask_service 单测：构造含五类单位标签 + 各类人名标签的文本，断言密文替换与还原无损；断言「设计说明」等不误报。
2. 预处理管线：zip 含 dwg/dxf/pdf/不支持文件 → 状态流转正确，产物齐全。
3. 重启恢复：人为留 processing/pending 记录，重启后状态正确。
4. 权限：非成员 403；普通用户访问超管接口 403。
5. 会话：expires_at 刷新逻辑；过期清理；恢复后上下文完整。
6. 端到端：建项目→传 zip→标记常用→成员问答（项目图纸+混传）→还原正确→5 天会话恢复。
7. 前端 Playwright：项目管理页流转、识图助手选择/切换/图纸集、会话恢复。

## 12. 实施拆分（供写实现计划参考）

1. 数据模型 + 迁移 + mask_service（含单测）
2. 预处理管线（zip 上传、worker、产物、重启恢复）
3. 项目管理 API + 图纸集 API + 权限
4. 问答链路改造（drawing_ids 入参、脱敏接入、5 天会话）
5. PC 前端（项目管理页 + 识图助手改造）
6. 移动端最小集
7. 清理任务 + 测试 + 部署
