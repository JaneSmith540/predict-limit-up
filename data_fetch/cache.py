"""
数据缓存层
SQLite 缓存已获取的数据，避免重复请求 Tushare API
"""

import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text

from config.settings import config


class DataCache:
    """
    数据缓存管理器

    用法:
        cache = DataCache()
        cache.save("daily_000001", df)
        df = cache.load("daily_000001", max_age_hours=24)
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_db()
        return cls._instance

    def _init_db(self):
        """初始化 SQLite 缓存数据库"""
        cache_path = config.get("data_source.cache.path", "data_cache/limitup.db")
        full_path = Path(config.get("data_source.cache.path", "data_cache/limitup.db"))
        if not full_path.is_absolute():
            full_path = Path("data_cache") / "limitup.db"
        full_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(f"sqlite:///{full_path}")
        self._create_table()

    def _create_table(self):
        """创建缓存表"""
        with self._engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS data_cache (
                    cache_key   TEXT PRIMARY KEY,
                    data        TEXT,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()

    @staticmethod
    def _make_key(prefix: str, params: dict) -> str:
        """生成缓存键"""
        param_str = str(sorted(params.items()))
        return f"{prefix}_{hashlib.md5(param_str.encode()).hexdigest()}"

    def save(self, key: str, df: pd.DataFrame):
        """保存 DataFrame 到缓存"""
        json_str = df.to_json(orient="records", date_format="iso")
        with self._engine.connect() as conn:
            conn.execute(text(
                "INSERT OR REPLACE INTO data_cache (cache_key, data, created_at) "
                "VALUES (:key, :data, :now)"
            ), {"key": key, "data": json_str, "now": datetime.now()})
            conn.commit()

    def load(self, key: str, max_age_hours: int = 24) -> Optional[pd.DataFrame]:
        """
        从缓存读取数据
        Args:
            key: 缓存键
            max_age_hours: 最大缓存时间（小时），超过则返回 None
        """
        with self._engine.connect() as conn:
            result = conn.execute(text(
                "SELECT data, created_at FROM data_cache WHERE cache_key = :key"
            ), {"key": key}).fetchone()

        if result is None:
            return None

        created_at = datetime.fromisoformat(str(result[1]).replace("Z", ""))
        if datetime.now() - created_at > timedelta(hours=max_age_hours):
            return None

        import json
        records = json.loads(result[0])
        return pd.DataFrame(records)

    def clear(self, older_than_days: int = 30):
        """清理过期缓存"""
        with self._engine.connect() as conn:
            conn.execute(text(
                "DELETE FROM data_cache WHERE created_at < :cutoff"
            ), {"cutoff": datetime.now() - timedelta(days=older_than_days)})
            conn.commit()
