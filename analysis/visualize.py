"""
可视化模块 —— 基于 matplotlib 的图表生成
"""
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # 非交互式后端，无需 GUI
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import pandas as pd


class Visualizer:
    """
    图表生成器，支持：
    - 柱状图 / 饼图 / 折线图 / 散点图
    - 词云
    - 直接保存为 PNG 文件
    """

    # ---- 字体设置 ----

    @staticmethod
    def _setup_chinese_font():
        """尝试设置中文字体，避免中文乱码"""
        candidates = [
            "Microsoft YaHei", "SimHei", "KaiTi", "SimSun",
            "Noto Sans CJK SC", "WenQuanYi Micro Hei",
            "Arial Unicode MS", "PingFang SC",
        ]
        available = {f.name for f in fm.fontManager.ttflist}
        for font in candidates:
            if font in available:
                plt.rcParams["font.sans-serif"] = [font, "DejaVu Sans"]
                plt.rcParams["axes.unicode_minus"] = False
                return
        # 尝试用 sans-serif 兜底
        plt.rcParams["font.sans-serif"] = ["sans-serif"]

    # ---- 柱状图 ----

    @classmethod
    def bar(
        cls,
        labels: list[str],
        values: list[int | float],
        title: str = "柱状图",
        xlabel: str = "",
        ylabel: str = "",
        save_path: str | Path = None,
        figsize: tuple = (12, 6),
        color: str = "#4A90D9",
        rotate_x: int = 0,
    ) -> Optional[Path]:
        """绘制柱状图并保存"""
        cls._setup_chinese_font()
        fig, ax = plt.subplots(figsize=figsize)

        bars = ax.bar(range(len(labels)), values, color=color, edgecolor="white", linewidth=0.5)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=rotate_x, ha="right" if rotate_x else "center")
        ax.set_title(title, fontsize=16, fontweight="bold")
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        # 数值标签
        for bar_obj, val in zip(bars, values):
            ax.text(bar_obj.get_x() + bar_obj.get_width() / 2, bar_obj.get_height() + max(values) * 0.01,
                    str(val), ha="center", va="bottom", fontsize=9)

        plt.tight_layout()
        return cls._save(save_path)

    # ---- 饼图 ----

    @classmethod
    def pie(
        cls,
        labels: list[str],
        values: list[int | float],
        title: str = "饼图",
        save_path: str | Path = None,
        figsize: tuple = (10, 8),
    ) -> Optional[Path]:
        """绘制饼图"""
        cls._setup_chinese_font()
        fig, ax = plt.subplots(figsize=figsize)

        wedges, texts, autotexts = ax.pie(
            values, labels=labels, autopct="%1.1f%%",
            startangle=90, pctdistance=0.85,
            colors=plt.cm.Set3(range(len(labels))),
        )
        ax.set_title(title, fontsize=16, fontweight="bold")
        plt.setp(autotexts, size=9, weight="bold")

        plt.tight_layout()
        return cls._save(save_path)

    # ---- 折线图 ----

    @classmethod
    def line(
        cls,
        x: list,
        y: list[int | float],
        title: str = "折线图",
        xlabel: str = "",
        ylabel: str = "",
        save_path: str | Path = None,
        figsize: tuple = (12, 6),
        color: str = "#E74C3C",
    ) -> Optional[Path]:
        """绘制折线图"""
        cls._setup_chinese_font()
        fig, ax = plt.subplots(figsize=figsize)

        ax.plot(x, y, marker="o", linewidth=2, markersize=6, color=color)
        ax.set_title(title, fontsize=16, fontweight="bold")
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", alpha=0.3)

        plt.tight_layout()
        return cls._save(save_path)

    # ---- 散点图 ----

    @classmethod
    def scatter(
        cls,
        x: list[int | float],
        y: list[int | float],
        title: str = "散点图",
        xlabel: str = "",
        ylabel: str = "",
        save_path: str | Path = None,
        figsize: tuple = (10, 8),
        color: str = "#2ECC71",
        alpha: float = 0.6,
    ) -> Optional[Path]:
        """绘制散点图"""
        cls._setup_chinese_font()
        fig, ax = plt.subplots(figsize=figsize)

        ax.scatter(x, y, c=color, alpha=alpha, edgecolors="white", linewidth=0.5)
        ax.set_title(title, fontsize=16, fontweight="bold")
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        plt.tight_layout()
        return cls._save(save_path)

    # ---- 词云 ----

    @classmethod
    def wordcloud(
        cls,
        word_freq: list[tuple[str, int]],
        title: str = "词云",
        save_path: str | Path = None,
        figsize: tuple = (14, 10),
        width: int = 1200,
        height: int = 800,
    ) -> Optional[Path]:
        """
        生成词云图。
        word_freq: [("Python", 50), ("爬虫", 30), ...]
        """
        cls._setup_chinese_font()
        try:
            from wordcloud import WordCloud
        except ImportError:
            print("[警告] 未安装 wordcloud 库，请 pip install wordcloud")
            return None

        wc = WordCloud(
            width=width, height=height,
            background_color="white",
            font_path=cls._find_chinese_font_path(),
            max_words=200,
            collocations=False,
        )
        wc.generate_from_frequencies(dict(word_freq))

        fig, ax = plt.subplots(figsize=figsize)
        ax.imshow(wc, interpolation="bilinear")
        ax.axis("off")
        ax.set_title(title, fontsize=20, fontweight="bold")

        plt.tight_layout()
        return cls._save(save_path)

    # ---- 从 DataFrame 快速生成 ----

    @classmethod
    def from_value_counts(
        cls,
        df: pd.DataFrame,
        column: str,
        chart_type: str = "bar",
        top_n: int = 20,
        title: str = None,
        save_path: str | Path = None,
    ) -> Optional[Path]:
        """根据 DataFrame 某列的值分布快速生成图表"""
        counts = df[column].value_counts().head(top_n)
        title = title or f"{column} 分布 Top {top_n}"

        if chart_type == "bar":
            return cls.bar(
                labels=counts.index.tolist(),
                values=counts.values.tolist(),
                title=title,
                rotate_x=45 if len(counts) > 10 else 0,
                save_path=save_path,
            )
        elif chart_type == "pie":
            return cls.pie(
                labels=counts.index.tolist(),
                values=counts.values.tolist(),
                title=title,
                save_path=save_path,
            )
        return None

    # ---- 工具 ----

    @classmethod
    def _save(cls, path: str | Path = None) -> Optional[Path]:
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(str(path), dpi=150, bbox_inches="tight", facecolor="white")
            plt.close()
            return Path(path)
        plt.close()
        return None

    @classmethod
    def _find_chinese_font_path(cls) -> Optional[str]:
        """查找系统中文字体路径"""
        candidates = ["msyh.ttc", "msyh.ttf", "simhei.ttf", "simsun.ttc"]
        for font in fm.fontManager.ttflist:
            if font.name in ("Microsoft YaHei", "SimHei", "SimSun"):
                return font.fname
        # Fallback: 搜索系统字体目录
        import os
        font_dirs = [
            r"C:\Windows\Fonts",
            "/usr/share/fonts",
            "/System/Library/Fonts",
        ]
        for d in font_dirs:
            if os.path.isdir(d):
                for root, _, files in os.walk(d):
                    for f in files:
                        if f.lower() in candidates:
                            return os.path.join(root, f)
        return None
