# -*- coding: utf-8 -*-
"""DJj03 定位失败归因对照实验（一次性脚本，跑完即删）。

问题: "办公楼 B-8-B-A 的这个位置的基础是什么尺寸？什么配筋？"
真相: DJj03, 350/350(阶高), 4000×4000, B: X&Y:Φ16@200

实验臂:
  A1 当前生产预算(单图): 总览+p1+p2
  A2 高预算: 总览+全部14片切片
  A3 仅 p1(基础平面布置图所在帧)
  B1 纯文本+保留每条标注坐标(无图): DJj/轴号/检索命中标注全带坐标
  B2 纯文本去重无坐标(当前生产文本路径, 对照)
"""
import base64
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import requests  # noqa: E402
from PIL import Image  # noqa: E402

WORK = Path(r"D:\桌面\小图兔\素材\测试图纸\_reprocess2")
FID = "pd_15470f51"
CTX = json.load(open(WORK / "out" / f"{FID}.json", encoding="utf-8"))
OVERVIEW = WORK / "src/opt/xiaotutu/data/drawing_uploads" / f"{FID}.png"
QUESTION = "办公楼 B-8-B-A 的这个位置的基础是什么尺寸？什么配筋？"

cfg = json.load(open(r"D:\桌面\小图兔\小图兔代码\data\app_config.json", encoding="utf-8"))
prov = cfg["providers"][cfg["drawing_provider_index"]]
URL = prov["base_url"].rstrip("/") + "/chat/completions"
HEADERS = {"Authorization": f"Bearer {prov['api_key']}", "Content-Type": "application/json"}
MODEL = prov["model"]

SYS_BASE = """你是一位资深的建筑图纸审查专家（高级工程师），拥有30年建筑设计和施工管理经验。
你正在分析一份CAD图纸（办公楼结构图纸0629.dwg）。
## 回答要求
- 基于图纸实际数据回答，不编造不存在的信息
- 如果图纸数据不足以回答问题，说明缺少什么信息
- 中文回答"""


def img_b64(path: Path, max_edge: int = 4096) -> str:
    im = Image.open(path).convert("RGB")
    if max(im.size) > max_edge:
        r = max_edge / max(im.size)
        im = im.resize((round(im.size[0] * r), round(im.size[1] * r)))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def call(system: str, content) -> str:
    # deepseek-flash 是推理模型：reasoning 计入 completion，4096 会被思维链吃光导致 content 为空
    payload = {"model": MODEL, "temperature": 0.5, "max_tokens": 12288,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": content}]}
    r = requests.post(URL, headers=HEADERS, json=payload, timeout=600)
    r.raise_for_status()
    d = r.json()
    u = d.get("usage") or {}
    print(f"    [tokens] prompt={u.get('prompt_tokens')} completion={u.get('completion_tokens')}"
          f" finish={d['choices'][0].get('finish_reason')}")
    msg = d["choices"][0]["message"]
    rc = msg.get("reasoning_content") or ""
    if rc:
        print(f"    [reasoning {len(rc)}字] 尾部: ...{rc[-300:]}")
    return msg.get("content") or "(空-思维链截断)"


def crop_b64(path: Path, box: tuple) -> str:
    im = Image.open(path).convert("RGB").crop(box)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def vision_arm(tag: str, pngs: list[Path], note: str = ""):
    print(f"\n{'='*20} {tag} {'='*20}")
    content = [{"type": "text", "text": QUESTION + note}]
    for p in pngs:
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64(p)}"}})
    sys_p = SYS_BASE
    if len(pngs) > 1:
        sys_p += ("\n\n附：图像依次为【整图总览】+【各图幅切片（按上→下、左→右阅读序）】；"
                  "问题涉及具体某张图幅时请优先对照对应切片。")
    ans = call(sys_p, content)
    print(ans[:1500])
    return ans


def coord_text(with_coords: bool) -> str:
    """构造文本上下文。with_coords=True 时保留每条标注坐标。"""
    anns = CTX.get("text_annotations") or []
    lines = []
    djj = [a for a in anns if "DJj" in (a.get("text") or "")]
    axis = [a for a in anns if a.get("layer") == "AXIS_NUM"]
    lines.append(f"## 全部 DJj 系列标注（{len(djj)} 条，未去重）"
                 + ("，格式: 文字 @(x,y)坐标 [图层]" if with_coords else ""))
    for a in djj:
        if with_coords:
            p = a["position"]
            lines.append(f"- {a['text']} @({p[0]:.0f},{p[1]:.0f}) [{a.get('layer')}]")
        else:
            lines.append(f"- {a['text']} [{a.get('layer')}]")
    lines.append(f"\n## 全部轴号标注（{len(axis)} 条）")
    for a in axis:
        if with_coords:
            p = a["position"]
            lines.append(f"- {a['text']} @({p[0]:.0f},{p[1]:.0f})")
        else:
            lines.append(f"- {a['text']}")
    return "\n".join(lines)


def text_arm(tag: str, with_coords: bool):
    print(f"\n{'='*20} {tag} {'='*20}")
    sys_p = SYS_BASE + "\n\n以下是该图纸的文字标注提取结果：\n" + coord_text(with_coords)
    if with_coords:
        sys_p += ("\n\n注：坐标为图纸绘图单位（mm），同一图幅内坐标可直接比较；"
                  "轴线交点即该位置。可据此推理标注的空间归属。")
    ans = call(sys_p, QUESTION)
    print(ans[:1500])
    return ans


arms = sys.argv[1:] or ["A1", "A2", "A3", "B1", "B2"]
slices = sorted((WORK / "out").glob(f"{FID}_p*.png"),
                key=lambda p: int(p.stem.split("_p")[1]))
if "A1" in arms:
    vision_arm("A1 当前预算: 总览+p1+p2", [OVERVIEW, slices[0], slices[1]])
if "A2" in arms:
    vision_arm("A2 高预算: 总览+全部14片", [OVERVIEW] + slices)
if "A3" in arms:
    vision_arm("A3 仅p1切片", [slices[0]])
if "B1" in arms:
    text_arm("B1 纯文本+坐标", True)
if "B2" in arms:
    text_arm("B2 纯文本去重无坐标(对照)", False)
if "A5" in arms:
    # p1 全图 + B-8×B-A 角部放大裁剪（像素坐标已按 4096×2893 目视标定）
    print(f"\n{'='*20} A5 p1+角部放大裁剪 {'='*20}")
    corner = crop_b64(slices[0], (2100, 700, 2950, 1500))
    content = [{"type": "text", "text": QUESTION +
                "\n\n附：第1张是基础平面布置图整幅，第2张是该图幅右下角区域"
                "（B-8轴与B-A轴交点附近）的放大裁剪，请结合两张图回答。"},
               {"type": "image_url", "image_url": {
                   "url": f"data:image/png;base64,{img_b64(slices[0])}"}},
               {"type": "image_url", "image_url": {
                   "url": f"data:image/png;base64,{corner}"}}]
    ans = call(SYS_BASE, content)
    print(ans[:1500])
