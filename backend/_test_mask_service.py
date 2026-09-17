# -*- coding: utf-8 -*-
"""mask_service 单元测试（pytest）：
- 五类单位标签 + 各类人名标签的密文替换与还原无损
- 「设计说明」等停用词不误报
- 最长匹配优先（【单位1】 vs 【单位10】 前缀冲突）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from services.mask_service import CipherMap, extract_entities, mask_text, restore_text


def roundtrip(text):
    cmap = CipherMap()
    masked = mask_text(text, cmap)
    return masked, restore_text(masked, cmap), cmap


def test_unit_labels_all_kinds():
    text = ("建设单位：武汉市第三建筑工程有限公司\n"
            "施工单位：中铁四局集团\n"
            "设计单位：中南建筑设计研究院\n"
            "监理单位：湖北诚信工程监理有限公司\n"
            "勘察单位：武汉地质工程勘察院")
    masked, restored, cmap = roundtrip(text)
    for kw in ("武汉市第三建筑工程有限公司", "中铁四局",
               "中南建筑设计研究院", "湖北诚信工程监理有限公司", "武汉地质工程勘察院"):
        assert kw not in masked, masked
        assert kw in cmap.units
    assert restored == text  # 还原无损


def test_person_labels():
    text = "制图：张伟\n校对：王芳芳\n审核：李国强\n审定：刘洋\n项目负责人：陈建军"
    masked, restored, cmap = roundtrip(text)
    for name in ("张伟", "王芳芳", "李国强", "刘洋", "陈建军"):
        assert name not in masked, masked
        assert name in cmap.persons
    assert restored == text


def test_design_shenming_no_false_positive():
    # 「设计说明」不应被当成人名；「设计」后无冒号/空格分隔也不误中
    text = "设计说明：本工程采用桩基础。详见国家标准规范。"
    masked, restored, cmap = roundtrip(text)
    assert masked == text
    assert cmap.persons == {}
    assert cmap.units == {}


def test_unit_suffix_in_body():
    text = "本工程由武汉建工集团股份有限公司承建，图纸由中南电力设计院提供。"
    masked, restored, cmap = roundtrip(text)
    assert "武汉建工集团股份有限公司" not in masked
    assert "中南电力设计院" not in masked
    assert restored == text


def test_bare_suffix_not_entity():
    # 裸后缀「股份有限公司」不构成实体
    assert extract_entities("股份有限公司") == []


def test_cross_drawing_consistent_token():
    # 同一项目内同一单位使用同一密文
    cmap = CipherMap()
    m1 = mask_text("建设单位：武汉建工集团", cmap)
    m2 = mask_text("施工单位：武汉建工集团", cmap)
    tok = cmap.units["武汉建工集团"]
    assert tok in m1 and tok in m2
    assert len(cmap.units) == 1


def test_longest_match_first():
    cmap = CipherMap()
    for i in range(12):
        mask_text(f"建设单位：{'测试' * (i + 1)}有限公司", cmap)
    masked, _restored, _c = roundtrip("建设单位：武汉第三建筑工程有限责任公司")
    # 构造前缀冲突：手动塞入 【单位1】/【单位10】 风格 token 验证 restore 最长匹配
    cmap2 = CipherMap({"units": {"甲公司": "【单位1】", "乙公司": "【单位10】"}, "persons": {}})
    assert restore_text("【单位10】和【单位1】", cmap2) == "乙公司和甲公司"


def test_unregistered_token_kept():
    cmap = CipherMap()
    assert restore_text("这是【单位99】的东西", cmap) == "这是【单位99】的东西"


def test_realtime_path_user_question_masked():
    # 实时上传路径：用户提问文本中的实体也被脱敏
    masked, restored, cmap = roundtrip("请问中铁四局集团的桩基布置有什么要求？")
    assert "中铁四局集团" not in masked
    assert restored == "请问中铁四局集团的桩基布置有什么要求？"


def test_real_drawing_false_positives():
    # 真实图纸（远景乌兰察布项目）抓出的误报回归
    cases = [
        "设计单位：依据建设单位提供的本工程项目的地质勘察报告及XXX的批文与意见",
        "- [图框] [0] 设计单位（×2）",
        "- [图框] [0] 共同验槽合格后方可（×2）",
        "本工程由建设单位组织验收后方可进行下道工序施工",
    ]
    for text in cases:
        _masked, _restored, cmap = roundtrip(text)
        bad = [r for r in list(cmap.units) + list(cmap.persons)
               if any(k in r for k in ("批文", "（×2）", "验槽", "组织"))]
        assert not bad, f"误报: {bad} <- {text}"


def test_label_without_colon_not_matched():
    # 标签后无冒号不再吞后续文字（如去重行「设计单位（×2）」）
    masked, _r, cmap = roundtrip("设计单位（×2）")
    assert cmap.units == {}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print(f"\n=== {len(fns)} 项全部通过 ===")
