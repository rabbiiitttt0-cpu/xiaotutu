"""图表渲染统一字体管理（CJK）

字体随仓库内置（assets/fonts/NotoSansSC-subset.ttf，OFL 协议），
本机 Windows 与云端 Linux 容器渲染效果一致。勿改用系统字体路径（两端不一致）。
"""
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FONT_PATH = WEB_ROOT / "assets" / "fonts" / "NotoSansSC-subset.ttf"

FONT_AVAILABLE = FONT_PATH.exists()


def pil_font(size: int):
    """PIL 用字体（truetype 按路径加载）"""
    from PIL import ImageFont
    return ImageFont.truetype(str(FONT_PATH), size)


def register_matplotlib():
    """matplotlib Agg 后端 + 内置字体注册（无显示环境安全）"""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager
    if FONT_PATH.exists():
        font_manager.fontManager.addfont(str(FONT_PATH))
        matplotlib.rcParams["font.family"] = "Noto Sans CJK SC"
    matplotlib.rcParams["axes.unicode_minus"] = False
