"""看图兔问答多 Agent 骨架（2026-09-26）

- LocateAgent（窗口A，纯文本）：三级定位 图纸→图幅→部位，输出结构化 JSON
- Snip 工具（services/snip_locate.py，零 LLM）：OCR/轴网/裁剪，把定位结论变成图
- QAAgent（窗口B，视觉）：只回答不定位，上下文 = 问题 + 生料包 + 历史
- ProfileAgent（窗口C，离线）：预处理期生成图纸摘要 + 批次关系图

设计红线：
- 任一 Agent 失败/超时/JSON 非法 → 返回 None，调用方静默回退既有链路
- 送 LLM 的文本必须是脱敏态（轴号/方位/图名非敏感实体，不受影响）
"""
from .base import run_agent, extract_json  # noqa: F401
