"""
数据库管理模块
SQLite 存储: 涨停历史、黑名单、交易记录、缓存数据
"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd
from sqlalchemy import create_engine, text

from config.settings import config, PROJECT_ROOT


class Database:
    """
    SQLite 数据库管理器

    表结构:
    - limit_up_history: 涨停历史记录
    - blacklist: 黑名单
    - trades: 交易记录
    - daily_signals: 每日信号记录
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        cache_path = config.get("data_source.cache.path", "data_cache/limitup.db")
        db_path = Path(cache_path)
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / "data_cache" / "limitup.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(f"sqlite:///{db_path}")
        self._create_tables()

    def _create_tables(self):
        """创建数据库表"""
        with self._engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS limit_up_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    close_price REAL,
                    limit_amount REAL,
                    seal_fund REAL,
                    open_times INTEGER,
                    first_limit_time TEXT,
                    last_limit_time TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS blacklist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_code TEXT NOT NULL,
                    reason TEXT,
                    stop_loss_count INTEGER DEFAULT 0,
                    blocked_until TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    direction TEXT,
                    price REAL,
                    volume INTEGER,
                    signal_level TEXT,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS daily_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    nfrm_score INTEGER,
                    lgm_score INTEGER,
                    ahs_score INTEGER,
                    signal_level TEXT,
                    win_probability REAL,
                    veto_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()

    def save_trade(self, ts_code: str, trade_date: str, direction: str,
                   price: float, volume: int, signal_level: str = "", reason: str = ""):
        """保存交易记录"""
        with self._engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO trades (ts_code, trade_date, direction, price, volume, "
                "signal_level, reason) VALUES (:code, :date, :dir, :price, :vol, :level, :reason)"
            ), {
                "code": ts_code, "date": trade_date, "dir": direction,
                "price": price, "vol": volume, "level": signal_level, "reason": reason,
            })
            conn.commit()

    def get_trades(self, start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """查询交易记录"""
        query = "SELECT * FROM trades WHERE 1=1"
        params = {}
        if start_date:
            query += " AND trade_date >= :start"
            params["start"] = start_date
        if end_date:
            query += " AND trade_date <= :end"
            params["end"] = end_date
        query += " ORDER BY trade_date"
        return pd.read_sql(text(query), self._engine, params=params)

    def save_limit_up_history(self, df: pd.DataFrame):
        """批量保存涨停历史"""
        df.to_sql("limit_up_history", self._engine, if_exists="append", index=False)

    def get_limit_up_history(self, ts_code: str = "", days: int = 180) -> pd.DataFrame:
        """查询涨停历史"""
        query = "SELECT * FROM limit_up_history WHERE 1=1"
        params = {}
        if ts_code:
            query += " AND ts_code = :code"
            params["code"] = ts_code
        query += f" ORDER BY trade_date DESC LIMIT {days}"
        return pd.read_sql(text(query), self._engine, params=params)
