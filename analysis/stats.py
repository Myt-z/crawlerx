"""
数据分析模块 —— 基于 pandas 的统计分析和数据清洗
"""
import json
from pathlib import Path
from collections import Counter
from typing import Optional

import pandas as pd


class DataAnalyzer:
    """
    数据分析器，支持：
    - 从 JSON/CSV/SQL 加载数据
    - 数据清洗（去重、缺失值处理）
    - 统计分析（词频、分组汇总、描述性统计）
    - 导出报告
    """

    def __init__(self, data: list[dict] | pd.DataFrame = None):
        if isinstance(data, pd.DataFrame):
            self.df = data
        elif data:
            self.df = pd.DataFrame(data)
        else:
            self.df = pd.DataFrame()

    # ---- 加载 ----

    @classmethod
    def from_json(cls, path: str | Path) -> "DataAnalyzer":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data)

    @classmethod
    def from_csv(cls, path: str | Path) -> "DataAnalyzer":
        df = pd.read_csv(path, encoding="utf-8-sig")
        return cls(df)

    @classmethod
    def from_db(cls, db_path: str | Path, table: str) -> "DataAnalyzer":
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
        conn.close()
        return cls(df)

    # ---- 数据清洗 ----

    def clean(self, drop_duplicates: bool = True, fill_na: str = "") -> "DataAnalyzer":
        df = self.df.copy()
        if drop_duplicates:
            df = df.drop_duplicates()
        if fill_na is not None:
            df = df.fillna(fill_na)
        return DataAnalyzer(df)

    def drop_columns(self, columns: list[str]) -> "DataAnalyzer":
        return DataAnalyzer(self.df.drop(columns=columns, errors="ignore"))

    def filter(self, column: str, value) -> "DataAnalyzer":
        return DataAnalyzer(self.df[self.df[column] == value])

    def filter_contains(self, column: str, keyword: str) -> "DataAnalyzer":
        return DataAnalyzer(self.df[self.df[column].astype(str).str.contains(keyword, na=False)])

    # ---- 统计分析 ----

    def summary(self) -> dict:
        """整体概览：行数、列数、各列类型、缺失值"""
        info = {
            "rows": len(self.df),
            "columns": len(self.df.columns),
            "memory_usage": f"{self.df.memory_usage(deep=True).sum() / 1024:.1f} KB",
            "dtypes": self.df.dtypes.astype(str).to_dict(),
            "missing": self.df.isnull().sum().to_dict(),
        }
        return info

    def describe(self, columns: list[str] = None) -> pd.DataFrame:
        """描述性统计（均值、方差、分位数等）"""
        target = self.df[columns] if columns else self.df
        return target.describe(include="all")

    def value_counts(self, column: str, top_n: int = 20) -> pd.DataFrame:
        """某列的值频率分布"""
        counts = self.df[column].value_counts().head(top_n).reset_index()
        counts.columns = [column, "count"]
        counts["percentage"] = (counts["count"] / len(self.df) * 100).round(2)
        return counts

    def group_stats(
        self, group_by: str, agg_rules: dict = None
    ) -> pd.DataFrame:
        """
        分组聚合。
        agg_rules: {"price": "mean", "title": "count"}
        """
        if agg_rules is None:
            agg_rules = {}
        if not agg_rules:
            # 默认所有数值列取均值
            numeric_cols = self.df.select_dtypes(include="number").columns.tolist()
            agg_rules = {c: "mean" for c in numeric_cols if c != group_by}
        return self.df.groupby(group_by).agg(agg_rules).reset_index()

    # ---- 文本分析 ----

    def word_frequency(self, column: str, top_n: int = 50, lang: str = "zh") -> list[tuple[str, int]]:
        """
        文本列词频统计。
        lang="zh" 使用 jieba 中文分词，否则按空格分词。
        """
        texts = self.df[column].dropna().astype(str).tolist()

        if lang == "zh":
            try:
                import jieba
                words = []
                for text in texts:
                    words.extend(jieba.cut(text))
            except ImportError:
                words = " ".join(texts).split()
        else:
            words = " ".join(texts).lower().split()

        # 过滤短词
        words = [w.strip() for w in words if len(w.strip()) >= 2]
        counter = Counter(words)
        return counter.most_common(top_n)

    # ---- 导出 ----

    def to_dataframe(self) -> pd.DataFrame:
        return self.df

    def to_dict(self) -> list[dict]:
        return self.df.to_dict(orient="records")

    def to_excel(self, path: str | Path):
        self.df.to_excel(str(path), index=False, engine="openpyxl")

    def to_csv(self, path: str | Path):
        self.df.to_csv(str(path), index=False, encoding="utf-8-sig")

    def to_json(self, path: str | Path, orient: str = "records"):
        self.df.to_json(str(path), orient=orient, force_ascii=False, indent=2)
