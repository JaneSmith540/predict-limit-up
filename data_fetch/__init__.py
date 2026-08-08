"""
数据获取模块 — 封装 Tushare API（带本地缓存）

使用方法:
    from data_fetch import data
    df = data.get_daily("000001.SZ", "20240101", "20240601")

缓存策略:
    - get_daily_all(trade_date): 按日期缓存到 data_cache/daily_all/{date}.pkl
    - get_daily(ts_code, start, end): 按 ts_code 缓存到 data_cache/daily/{ts_code}.pkl
    - get_limit_list_range(start, end): 缓存到 data_cache/limit_list.pkl
    - get_trade_cal(start, end): 缓存到 data_cache/trade_cal.pkl
    - 其他 API 不缓存（低频调用）
"""
import os
import pickle
from pathlib import Path

import tushare as ts
import pandas as pd
from utils import TUSHARE_TOKEN, get_config, log

# 缓存根目录
CACHE_DIR = Path(__file__).parent.parent / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)


def _cache_path(subdir: str, name: str) -> Path:
    """构建缓存文件路径"""
    d = CACHE_DIR / subdir
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{name}.pkl"


def _load_cache(subdir: str, name: str):
    """加载缓存，不存在返回 None"""
    p = _cache_path(subdir, name)
    if p.exists():
        try:
            with open(p, "rb") as f:
                return pickle.load(f)
        except Exception:
            return None
    return None


def _save_cache(subdir: str, name: str, data):
    """保存缓存"""
    p = _cache_path(subdir, name)
    try:
        with open(p, "wb") as f:
            pickle.dump(data, f)
    except Exception as e:
        log.debug(f"缓存保存失败 {p}: {e}")


class TushareAPI:
    """Tushare API 封装（带本地缓存）"""

    def __init__(self):
        if not TUSHARE_TOKEN:
            raise ValueError("TUSHARE_TOKEN 未设置，请创建 .env 文件并填入 token")
        ts.set_token(TUSHARE_TOKEN)
        self.api = ts.pro_api()
        log.info("Tushare API 初始化成功")

    def get_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取日线行情（不复权 — 避免前复权数据的隐性未来信息泄漏）

        缓存按 ts_code 存储，首次下载后缓存全部历史数据。
        后续调用从缓存读取，按 start_date/end_date 过滤。
        """
        # 尝试从缓存加载
        cached = _load_cache("daily", ts_code.replace(".", "_"))
        if cached is not None:
            df = cached
        else:
            df = self.api.daily(ts_code=ts_code, start_date="20230101", end_date="20261231")
            df = df.sort_values("trade_date").reset_index(drop=True)
            _save_cache("daily", ts_code.replace(".", "_"), df)

        # 按日期范围过滤
        df = df[(df["trade_date"] >= start_date) & (df["trade_date"] <= end_date)].copy()
        df = df.sort_values("trade_date").reset_index(drop=True)
        return df

    def get_daily_basic(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取每日指标（换手率、PE等）"""
        df = self.api.daily_basic(ts_code=ts_code, start_date=start_date, end_date=end_date)
        return df.sort_values("trade_date").reset_index(drop=True)

    def get_limit_list(self, trade_date: str) -> pd.DataFrame:
        """获取某日涨停股票列表"""
        return self.api.limit_list_d(trade_date=trade_date)

    def get_stock_list(self) -> pd.DataFrame:
        """获取全部在上市股票"""
        return self.api.stock_basic(list_status="L")

    def get_index_daily(self, ts_code: str = "000300.SH", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取指数日线（默认沪深300）"""
        return self.api.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)

    def get_top_list(self, trade_date: str) -> pd.DataFrame:
        """获取龙虎榜"""
        return self.api.top_list(trade_date=trade_date)

    def get_daily_all(self, trade_date: str) -> pd.DataFrame:
        """获取某天全市场所有股票的日线数据（不复权）

        按交易日缓存，后续调用直接从磁盘读取。
        """
        # 尝试从缓存加载
        cached = _load_cache("daily_all", trade_date)
        if cached is not None:
            return cached

        # 从 Tushare 下载
        df = self.api.daily(trade_date=trade_date)

        # 保存缓存
        _save_cache("daily_all", trade_date, df)
        return df

    def get_limit_list_range(self, start_date: str, end_date: str) -> pd.DataFrame:
        """获取一段时间内的所有涨停记录"""
        cache_name = f"{start_date}_{end_date}"
        cached = _load_cache("limit_list", cache_name)
        if cached is not None:
            return cached

        df = self.api.limit_list_d(start_date=start_date, end_date=end_date)
        _save_cache("limit_list", cache_name, df)
        return df

    def get_trade_cal(self, start_date: str, end_date: str) -> list:
        """获取交易日历"""
        cache_name = f"{start_date}_{end_date}"
        cached = _load_cache("trade_cal", cache_name)
        if cached is not None:
            return cached

        df = self.api.trade_cal(exchange="SSE", start_date=start_date, end_date=end_date)
        result = sorted(df[df["is_open"] == 1]["cal_date"].tolist())
        _save_cache("trade_cal", cache_name, result)
        return result


# 全局实例
data = TushareAPI()
