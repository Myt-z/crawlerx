"""CSV 存储后端 —— 适合 Excel 打开分析"""
import csv
from pathlib import Path
from typing import Optional


class CSVStorage:
    def __init__(self, filepath: str | Path):
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

    def save(self, data: list[dict], headers: Optional[list[str]] = None):
        """写入 CSV。headers 不指定则自动从数据中提取。"""
        if not data:
            return

        if headers is None:
            headers = list(data[0].keys())

        with open(self.filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(data)

    def save_rows(self, rows: list[list], headers: list[str]):
        """写入二维列表 + 表头"""
        with open(self.filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)

    def load(self) -> list[dict]:
        """读取 CSV 为字典列表"""
        if not self.filepath.exists():
            return []
        with open(self.filepath, "r", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
