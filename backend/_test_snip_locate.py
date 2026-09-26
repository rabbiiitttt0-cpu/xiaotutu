# -*- coding: utf-8 -*-
"""snip_locate / agents.base 单元测试（本地跑，不依赖服务与 LLM）。

用法: cd backend && python _test_snip_locate.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from services.snip_locate import (  # noqa: E402
    parse_location_spec, normalize_axis, find_axis_intersection,
    find_table_region, direction_box, _cluster_1d, _median_spacing,
)
from services.agents.base import extract_json  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")
    if not cond:
        FAILED.append(name)


# ---------- parse_location_spec ----------
r = parse_location_spec("B-8轴交B-A轴的基础的尺寸和配筋")
norms = {a["norm"] for a in r["axes"]}
check("解析 B-8交B-A", norms == {"8", "A"}, str(r))

r = parse_location_spec("办公楼 B-8-B-A 的这个位置的基础是什么尺寸？")
norms = {a["norm"] for a in r["axes"]}
check("解析 B-8-B-A 连写", norms == {"8", "A"}, str(r))

r = parse_location_spec("8轴交A轴的柱子截面多大")
norms = {a["norm"] for a in r["axes"]}
check("解析 8轴交A轴", norms == {"8", "A"}, str(r))

r = parse_location_spec("左上角的雨棚详图标高多少")
check("方位词 左上", "左上" in r["directions"], str(r))

r = parse_location_spec("这套图讲了什么")
check("泛泛问题无轴号", not r["axes"] and not r["directions"], str(r))

# ---------- normalize_axis ----------
check("归一化 B-8", normalize_axis("B-8") == "8")
check("归一化 8-8(OCR误识)", normalize_axis("8-8") == "8")
check("归一化 8-A", normalize_axis("8-A") == "A")
check("归一化全角破折号", normalize_axis("B－8") == "8")

# ---------- _cluster_1d / _median_spacing ----------
check("一维聚类", _cluster_1d([100, 105, 300, 302, 700]) == [102.5, 301.0, 700.0])
check("中位间距", _median_spacing([100, 300, 500, 700]) == 200)

# ---------- find_axis_intersection ----------
items = []
for i, x in enumerate([100, 300, 500, 700], 1):  # 列轴 1-4（两端各一个标签）
    items.append({"text": str(i), "cx": float(x), "cy": 50.0})
    items.append({"text": str(i), "cx": float(x), "cy": 950.0})
for j, y in enumerate([200, 400, 600]):  # 行轴 A-C
    items.append({"text": chr(ord("A") + j), "cx": 30.0, "cy": float(y)})
    items.append({"text": chr(ord("A") + j), "cx": 970.0, "cy": float(y)})

inter = find_axis_intersection(items, ["3", "B"])
check("轴交点 (3,B)", inter and abs(inter["x"] - 500) < 5 and abs(inter["y"] - 400) < 5,
      str(inter))
check("列间距", inter and abs(inter["col_spacing"] - 200) < 1, str(inter))

# 目标轴缺失（图纸有 1-4 轴，问 5 轴）→ 等距外推 x≈900
inter = find_axis_intersection(items, ["5", "A"])
check("缺轴外推 (5,A)", inter and abs((inter["x"] or 0) - 900) < 5, str(inter))

inter = find_axis_intersection(items, ["X", "Y"])
check("无命中返回None", inter is None, str(inter))

# ---------- find_table_region ----------
tbl = [{"text": f"DJj0{i} 配筋", "cx": 800.0 + i * 10, "cy": 300.0 + i * 12}
       for i in range(1, 5)]
box = find_table_region(tbl + items, ["DJj"])
check("表格聚簇", box is not None and box[0] <= 810 and box[2] >= 840, str(box))
check("无关键词命中", find_table_region(items, ["DJj"]) is None)

# ---------- direction_box ----------
b = direction_box("右上", 4000, 3000)
check("方位框 右上", b == (2000, 0, 4000, 1500), str(b))
check("方位词未知", direction_box("天边", 4000, 3000) is None)

# ---------- extract_json ----------
check("裸JSON", extract_json('{"a": 1}') == {"a": 1})
check("围栏JSON", extract_json('```json\n{"a": 1}\n```') == {"a": 1})
check("解释文字包裹", extract_json('好的，结果如下：\n{"a": 1}\n以上') == {"a": 1})
check("数组", extract_json('[1, 2]') == [1, 2])
check("非法JSON", extract_json("我不知道") is None)
check("空串", extract_json("") is None)

print()
if FAILED:
    print(f"失败 {len(FAILED)} 项: {FAILED}")
    sys.exit(1)
print("全部通过")
