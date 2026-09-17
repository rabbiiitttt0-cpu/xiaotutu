"""脱敏服务：图纸文字层敏感信息（单位名/人名）→ 密文对照替换

- 识别：标签驱动（建设单位/施工单位/...：XXX、制图/审核/...：张三）
        + 单位后缀兜底（...有限公司/研究院/设计院/集团/工程局）
- 密文：【单位N】/【人名N】，对照表项目级持久化（同项目跨图纸同一密文，保证上下文一致）
- 链路：LLM 只见脱敏文本；输出给用户前 restore_text 还原
- 对照表只存服务端 data/projects/{pid}/cipher_map.json，任何 API 不返回
"""
import json
import os
import re
import threading
from pathlib import Path

# ---------- 识别规则 ----------

# 单位：标签后的一整段（图签栏样式「建设单位：XXX公司」），或正文中的单位后缀实体
_UNIT_LABEL_RE = re.compile(
    r"(建设单位|施工单位|设计单位|监理单位|勘察单位|代建单位|咨询单位|业主单位)"
    r"[\s]*[:：]?\s*([^\s，。；;、：:]{2,30})"
)
_UNIT_SUFFIX_RE = re.compile(
    r"[一-龥]{2,25}?(?:有限责任公司|股份有限公司|集团有限公司|有限公司|研究院|设计院|工程局|建工集团)"
)
# 人名：标签后 2~4 个连续汉字（制图:张三 / 审核：张工）。「设计」标签置后且要求冒号或空格分隔，
# 防止「设计说明」误中（说明在停用词里也做了兜底）
_PERSON_LABEL_RE = re.compile(
    r"(项目负责人|专业负责人|专业负责|项目总工|制图|绘图|校对|审核|审定|复核|会签|编制|设计)"
    r"[\s]*[:：]\s*([一-龥]{2,4})|"
    r"(项目负责人|专业负责人|专业负责|项目总工|制图|绘图|校对|审核|审定|复核|会签|编制)"
    r"\s+([一-龥]{2,4})"
)
# 人名停用词：标签后紧跟的常见非人名词
_PERSON_STOP = {
    "说明", "单位", "依据", "深度", "范围", "原则", "要求", "图纸", "阶段", "名称",
    "规范", "标准", "内容", "编号", "日期", "比例", "图号", "版本", "见下", "详见",
    "本院", "本所", "我司", "本工程",
}
# 单位停用词：纯通用后缀不构成实体（防「股份有限公司」这种裸后缀被当成单位）
_UNIT_STOP = {
    "有限公司", "有限责任公司", "股份有限公司", "集团有限公司",
    "研究院", "设计院", "工程局", "建工集团", "集团",
}

_TOKEN_PREFIX = {"unit": "【单位", "person": "【人名"}


class CipherMap:
    """密文对照表：real -> token 双向映射（units / persons 分开编号）"""

    def __init__(self, data: dict | None = None):
        data = data or {}
        self.units: dict = data.get("units", {})       # real -> 【单位N】
        self.persons: dict = data.get("persons", {})   # real -> 【人名N】

    def to_dict(self) -> dict:
        return {"units": self.units, "persons": self.persons}

    def token_for(self, kind: str, real: str) -> str:
        table = self.units if kind == "unit" else self.persons
        if real not in table:
            table[real] = f"{_TOKEN_PREFIX[kind]}{len(table) + 1}】"
        return table[real]

    def reverse_pairs(self) -> list[tuple[str, str]]:
        """(token, real) 列表，token 长的在前（防 【单位1】 抢先替换 【单位10】）"""
        pairs = [(t, r) for r, t in self.units.items()]
        pairs += [(t, r) for r, t in self.persons.items()]
        pairs.sort(key=lambda p: len(p[0]), reverse=True)
        return pairs


def extract_entities(text: str) -> list[tuple[str, str]]:
    """从一段文本中识别敏感实体，返回 [(kind, value)]（kind: unit/person）"""
    found: list[tuple[str, str]] = []
    if not text:
        return found
    for m in _UNIT_LABEL_RE.finditer(text):
        value = m.group(2).strip("，。；;、 ")
        if len(value) >= 2 and value not in _UNIT_STOP:
            found.append(("unit", value))
    for m in _UNIT_SUFFIX_RE.finditer(text):
        if m.group(0) not in _UNIT_STOP:
            found.append(("unit", m.group(0)))
    for m in _PERSON_LABEL_RE.finditer(text):
        value = m.group(2) or m.group(4) or ""
        if value and value not in _PERSON_STOP and not value.endswith(("单位", "说明")):
            found.append(("person", value))
    return found


def mask_text(text: str, cmap: CipherMap) -> str:
    """识别敏感实体 → 登记对照表 → 全文替换为密文（含此前已登记实体的替换）"""
    if not text:
        return text
    for kind, value in extract_entities(text):
        cmap.token_for(kind, value)
    masked = text
    # 长的真实名优先替换（防子串误替换）
    reals = sorted(list(cmap.units.items()) + list(cmap.persons.items()),
                   key=lambda p: len(p[0]), reverse=True)
    for real, token in reals:
        masked = masked.replace(real, token)
    return masked


def mask_info(info: dict, cmap: CipherMap) -> dict:
    """对解析结果 info 的文字层整体脱敏，返回脱敏后的副本（原 dict 不变）。
    覆盖：description / title_block / ocr_text / text_annotations[].text"""
    out = dict(info)
    for key in ("description", "title_block", "ocr_text"):
        if isinstance(info.get(key), str) and info[key]:
            out[key] = mask_text(info[key], cmap)
    annotations = info.get("text_annotations")
    if annotations:
        out["text_annotations"] = [
            {**a, "text": mask_text(a.get("text", ""), cmap)} for a in annotations
        ]
    return out


def restore_text(text: str, cmap: CipherMap) -> str:
    """把 LLM 输出中的密文还原为真实名称（未登记的密文样式原样保留，不臆造）"""
    if not text:
        return text
    for token, real in cmap.reverse_pairs():
        text = text.replace(token, real)
    return text


# ---------- 项目级对照表持久化 ----------

_lock = threading.Lock()


def load_project_cipher(project_dir: Path) -> CipherMap:
    p = project_dir / "cipher_map.json"
    if p.exists():
        try:
            return CipherMap(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return CipherMap()


def save_project_cipher(project_dir: Path, cmap: CipherMap):
    project_dir.mkdir(parents=True, exist_ok=True)
    tmp = project_dir / "cipher_map.json.tmp"
    tmp.write_text(json.dumps(cmap.to_dict(), ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(project_dir / "cipher_map.json"))


def mask_and_persist(text: str, project_dir: Path) -> str:
    """问答时对用户提问做脱敏并持久化新增实体（线程安全，worker 串行 + 问答并发都要安全）"""
    with _lock:
        cmap = load_project_cipher(project_dir)
        masked = mask_text(text, cmap)
        save_project_cipher(project_dir, cmap)
    return masked
