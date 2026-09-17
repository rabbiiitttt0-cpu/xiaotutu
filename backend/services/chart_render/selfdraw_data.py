"""matplotlib 数据类图表：pie / bar / line / pareto

Agg 无头后端；内置 CJK 字体；固定调色板与系统主色一致。
"""
from pathlib import Path

from .fonts import register_matplotlib

PALETTE = ["#409EFF", "#67C23A", "#E6A23C", "#F56C6C",
           "#909399", "#9B59B6", "#36CFC9", "#FF85C0"]


def render_data_chart(spec: dict, out_path: Path):
    register_matplotlib()
    import matplotlib.pyplot as plt

    ctype = spec["type"]
    data = spec["data"]
    labels = data["labels"]
    series = data["series"]

    fig, ax = plt.subplots(figsize=(9, 5.5), dpi=160)

    if ctype == "pie":
        values = series[0]["values"]
        colors = [PALETTE[i % len(PALETTE)] for i in range(len(labels))]
        ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90,
               colors=colors, textprops={"fontsize": 11})
        ax.set_aspect("equal")

    elif ctype == "bar":
        import numpy as np
        x = np.arange(len(labels))
        n_series = len(series)
        width = 0.7 / n_series
        for si, s in enumerate(series):
            bars = ax.bar(x + si * width - 0.35 + width / 2, s["values"],
                          width, label=s["name"] or None,
                          color=PALETTE[si % len(PALETTE)])
            ax.bar_label(bars, fmt="%.0f", fontsize=9)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=10)
        if n_series > 1 or series[0]["name"]:
            ax.legend(fontsize=9)
        ax.spines[["top", "right"]].set_visible(False)

    elif ctype == "line":
        for si, s in enumerate(series):
            ax.plot(labels, s["values"], marker="o",
                    label=s["name"] or None,
                    color=PALETTE[si % len(PALETTE)], linewidth=2)
        if len(series) > 1 or series[0]["name"]:
            ax.legend(fontsize=9)
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.spines[["top", "right"]].set_visible(False)
        plt.setp(ax.get_xticklabels(), rotation=20, ha="right", fontsize=10)

    elif ctype == "pareto":
        import numpy as np
        values = series[0]["values"]
        pairs = sorted(zip(labels, values), key=lambda p: -p[1])
        slabels = [p[0] for p in pairs]
        svalues = [p[1] for p in pairs]
        total = sum(svalues) or 1
        cum = np.cumsum(svalues) / total * 100

        bars = ax.bar(range(len(slabels)), svalues, color=PALETTE[0])
        ax.bar_label(bars, fmt="%.0f", fontsize=9)
        ax.set_xticks(range(len(slabels)))
        ax.set_xticklabels(slabels, fontsize=10)
        ax.spines[["top"]].set_visible(False)

        ax2 = ax.twinx()
        ax2.plot(range(len(slabels)), cum, marker="o", color=PALETTE[3], linewidth=2)
        ax2.axhline(80, linestyle="--", color="#909399", linewidth=1)
        ax2.set_ylim(0, 110)
        ax2.set_ylabel("累计百分比 (%)", fontsize=10)
        ax2.spines[["top"]].set_visible(False)
        plt.setp(ax.get_xticklabels(), rotation=20, ha="right")

    else:
        raise ValueError(f"非数据类图型: {ctype}")

    if spec.get("title"):
        fig.suptitle(spec["title"], fontsize=14)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
