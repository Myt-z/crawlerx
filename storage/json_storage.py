"""JSON 存储后端"""
import json
from pathlib import Path
from typing import Any


class JSONStorage:
    def __init__(self, filepath: str | Path):
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

    def save(self, data: Any, indent: int = 2) -> Path:
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        return self.filepath

    def load(self) -> Any:
        if self.filepath.exists():
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def append(self, new_items: list):
        """追加数据到已有 JSON 数组"""
        existing = self.load()
        if isinstance(existing, list):
            existing.extend(new_items)
        else:
            existing = new_items
        self.save(existing)
