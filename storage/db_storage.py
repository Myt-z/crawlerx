"""SQLite 存储后端 —— 支持查询和增量写入"""
import json
import sqlite3
from pathlib import Path
from typing import Optional, Any


class DBStorage:
    """
    轻量 SQLite 存储，无需安装数据库服务。
    自动建表、支持 upsert。
    """

    def __init__(self, db_path: str | Path = None):
        self.db_path = Path(db_path) if db_path else None
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self, db_path: str | Path = None):
        path = db_path or self.db_path
        if path is None:
            raise ValueError("db_path 未设置")
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        return self.conn

    # ---- 建表 ----

    def create_table(self, table: str, columns: dict[str, str], auto_id: bool = True):
        """
        自动建表。
        columns: {"title": "TEXT", "price": "REAL", "count": "INTEGER"}
        """
        col_defs = ["id INTEGER PRIMARY KEY AUTOINCREMENT"] if auto_id else []
        col_defs += [f'"{k}" {v}' for k, v in columns.items()]
        ddl = f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(col_defs)})'
        self.conn.execute(ddl)
        self.conn.commit()

    def create_table_from_data(self, table: str, sample: dict):
        """根据数据样本自动推断列类型并建表"""
        type_map = {
            int: "INTEGER", float: "REAL", bool: "INTEGER",
            str: "TEXT", type(None): "TEXT",
        }
        # 如果有 list/dict 则存为 TEXT (JSON)
        columns = {}
        for k, v in sample.items():
            if isinstance(v, (list, dict)):
                columns[k] = "TEXT"
            else:
                columns[k] = type_map.get(type(v), "TEXT")
        self.create_table(table, columns)

    # ---- 写入 ----

    def insert(self, table: str, data: dict | list[dict]):
        """插入数据（单条或批量）"""
        items = data if isinstance(data, list) else [data]
        if not items:
            return

        cols = list(items[0].keys())
        placeholders = ", ".join(["?" for _ in cols])
        col_names = ", ".join(f'"{c}"' for c in cols)
        sql = f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders})'

        rows = []
        for item in items:
            row = []
            for c in cols:
                v = item[c]
                row.append(json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
            rows.append(row)

        self.conn.executemany(sql, rows)
        self.conn.commit()

    def upsert(self, table: str, data: dict, unique_keys: list[str]):
        """存在则更新，不存在则插入"""
        cols = list(data.keys())
        placeholders = ", ".join(["?" for _ in cols])
        col_names = ", ".join(f'"{c}"' for c in cols)
        update_part = ", ".join(f'"{c}" = excluded."{c}"' for c in cols if c not in unique_keys)

        sql = (
            f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders}) '
            f'ON CONFLICT ({", ".join(unique_keys)}) DO UPDATE SET {update_part}'
        )
        row = [json.dumps(data[c], ensure_ascii=False) if isinstance(data[c], (list, dict)) else data[c] for c in cols]
        self.conn.execute(sql, row)
        self.conn.commit()

    # ---- 查询 ----

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        """执行任意 SQL 查询"""
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def select_all(self, table: str, limit: int = 0, offset: int = 0) -> list[dict]:
        sql = f'SELECT * FROM "{table}"'
        if limit > 0:
            sql += f" LIMIT {limit} OFFSET {offset}"
        return self.query(sql)

    def count(self, table: str, where: str = "") -> int:
        sql = f'SELECT COUNT(*) as cnt FROM "{table}"'
        if where:
            sql += f" WHERE {where}"
        rows = self.query(sql)
        return rows[0]["cnt"] if rows else 0

    # ---- 资源 ----

    def close(self):
        if self.conn:
            self.conn.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()
