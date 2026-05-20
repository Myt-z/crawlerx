"""
JSON / API 数据解析器 —— 适用于 REST API 返回的 JSON 数据
"""
import json
from typing import Any, Optional


class JSONParser:
    """
    JSON 数据提取器，支持用点号路径（dot notation）访问嵌套字段。
    例如: "data.list.0.title" → obj["data"]["list"][0]["title"]
    """

    @staticmethod
    def parse(text: str) -> Any:
        """解析 JSON 字符串为 Python 对象"""
        return json.loads(text)

    @staticmethod
    def extract(data: dict | list, path: str, default: Any = None) -> Any:
        """
        按路径提取值，支持点号表示法和数组索引。

        示例:
        - "name"              → data["name"]
        - "user.profile.age"  → data["user"]["profile"]["age"]
        - "items.0.title"     → data["items"][0]["title"]
        """
        keys = path.split(".")
        current = data
        for key in keys:
            try:
                if isinstance(current, list):
                    idx = int(key)
                    current = current[idx]
                else:
                    current = current[key]
            except (KeyError, IndexError, TypeError, ValueError):
                return default
        return current

    @staticmethod
    def extract_list(data: dict | list, path: str) -> list:
        """提取列表字段"""
        result = JSONParser.extract(data, path)
        if result is None:
            return []
        return result if isinstance(result, list) else [result]

    @staticmethod
    def flatten(data: dict, parent_key: str = "", sep: str = ".") -> dict:
        """将嵌套 JSON 扁平化为单层字典"""
        items = {}
        for key, value in data.items():
            new_key = f"{parent_key}{sep}{key}" if parent_key else key
            if isinstance(value, dict):
                items.update(JSONParser.flatten(value, new_key, sep))
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        items.update(JSONParser.flatten(item, f"{new_key}{sep}{i}", sep))
                    else:
                        items[f"{new_key}{sep}{i}"] = item
            else:
                items[new_key] = value
        return items

    @staticmethod
    def find_keys(data: dict, target_key: str) -> list[Any]:
        """递归搜索所有匹配 key 的值"""
        results = []
        if isinstance(data, dict):
            for k, v in data.items():
                if k == target_key:
                    results.append(v)
                if isinstance(v, (dict, list)):
                    results.extend(JSONParser.find_keys(v, target_key))
        elif isinstance(data, list):
            for item in data:
                results.extend(JSONParser.find_keys(item, target_key))
        return results

    @staticmethod
    def to_table(data: list[dict]) -> tuple[list[str], list[list]]:
        """将 JSON 列表转为表头+数据行（方便转 CSV/DataFrame）"""
        if not data:
            return [], []
        headers = list(data[0].keys())
        rows = [[row.get(h, "") for h in headers] for row in data]
        return headers, rows
