# -*- coding: utf-8 -*-
"""一期优化回归测试：图片规范化并行(#3)
无 pytest 也能跑：python _test_img_parallel.py

要求：并行结果与串行逐张完全一致（顺序、内容），失败项同样为 None 且不中断整批。
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PIL import Image

from api.drawing import _img_data_urls_parallel, _img_data_urls_from_bytes, _img_data_url_from_path


def _make_fixtures(tmp: Path) -> list[Path]:
    paths = []
    # ① 普通 RGB PNG（无需重编码）
    p1 = tmp / "rgb.png"
    Image.new("RGB", (64, 64), (200, 100, 50)).save(p1)
    paths.append(p1)
    # ② 透明 RGBA（须合成白底 → 重编码 JPEG）
    p2 = tmp / "rgba.png"
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    im.putpixel((10, 10), (255, 0, 0, 128))
    im.save(p2)
    paths.append(p2)
    # ③ 超大单边（>4096 → 降采样）
    p3 = tmp / "big.png"
    Image.new("RGB", (5000, 100), (0, 128, 0)).save(p3)
    paths.append(p3)
    # ④ 非法文件（魔数不符 → None）
    p4 = tmp / "bad.png"
    p4.write_bytes(b"NOT_AN_IMAGE_AT_ALL")
    paths.append(p4)
    return paths


def test_parallel_equals_serial():
    with tempfile.TemporaryDirectory() as td:
        paths = _make_fixtures(Path(td))
        serial = [_img_data_url_from_path(p) for p in paths]
        assert serial[0] and serial[1] and serial[2], "前置：合法图应产出 dataURL"
        assert serial[3] is None, "前置：非法文件应为 None"
        parallel = _img_data_urls_parallel(paths)
        assert parallel == serial, "并行结果必须与串行逐字节一致（含顺序与 None）"


def test_bytes_variant_equals_path_variant():
    with tempfile.TemporaryDirectory() as td:
        paths = _make_fixtures(Path(td))
        serial = [_img_data_url_from_path(p) for p in paths]
        items = [(p.read_bytes(), p.name) for p in paths]
        out = _img_data_urls_from_bytes(items)
        assert out == serial, "bytes 版与 path 版结果必须一致"


def test_single_item_bypass():
    with tempfile.TemporaryDirectory() as td:
        paths = _make_fixtures(Path(td))
        out = _img_data_urls_parallel(paths[:1])
        assert out == [_img_data_url_from_path(paths[0])], "单张应走原函数且结果一致"


ALL_TESTS = [
    test_parallel_equals_serial,
    test_bytes_variant_equals_path_variant,
    test_single_item_bypass,
]

if __name__ == "__main__":
    failed = 0
    for t in ALL_TESTS:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(ALL_TESTS) - failed}/{len(ALL_TESTS)} passed")
    sys.exit(1 if failed else 0)
