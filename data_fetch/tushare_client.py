"""
Tushare 数据客户端封装
统一管理 API 调用、频率限制、错误重试
"""

import time
import functools
from typing import Any, Dict, List, Optional

import tushare as ts

from config.settings import config


def _rate_limit(calls_per_minute: int = 200):
    """API 频率限制装饰器"""
    min_interval = 60.0 / calls_per_minute

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            elapsed = time.time() - wrapper._last_call
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            result = func(*args, **kwargs)
            wrapper._last_call = time.time()
            return result
        wrapper._last_call = 0.0
        return wrapper
    return decorator


class TushareClient:
    """
    Tushare API 统一客户端

    用法:
        client = TushareClient()
        df = client.daily(ts_code="000001.SZ", start_date="20260101")
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_api()
        return cls._instance

    def _init_api(self):
        """初始化 Tushare pro API"""
        ts.set_token(config.tushare_token)
        self._api = ts.pro_api()

    # ============================================================
    # 行情数据
    # ============================================================

    def daily(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
    ):
        """日线行情"""
        return self._api.daily(
            ts_code=ts_code,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
        )

    def daily_basic(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
    ):
        """每日指标（PE/PB/换手率等）"""
        return self._api.daily_basic(
            ts_code=ts_code,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
        )

    def stk_mins(self, ts_code: str, start_date: str, end_date: str, freq: str = "1min"):
        """分钟线数据（需要较高积分权限）"""
        return self._api.stk_mins(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            freq=freq,
        )

    # ============================================================
    # 涨停/异动数据
    # ============================================================

    def limit_list_d(self, trade_date: str = "", start_date: str = "", end_date: str = ""):
        """每日涨停板统计"""
        return self._api.limit_list_d(
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
        )

    def stk_limit(self, ts_code: str = "", trade_date: str = ""):
        """涨跌停价格"""
        return self._api.stk_limit(ts_code=ts_code, trade_date=trade_date)

    def moneyflow(self, ts_code: str = "", trade_date: str = "", start_date: str = "", end_date: str = ""):
        """个股资金流向"""
        return self._api.moneyflow(
            ts_code=ts_code,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
        )

    # ============================================================
    # 龙虎榜数据
    # ============================================================

    def top_list(self, trade_date: str = "", ts_code: str = ""):
        """龙虎榜每日明细"""
        return self._api.top_list(trade_date=trade_date, ts_code=ts_code)

    def top_inst(self, trade_date: str = "", ts_code: str = ""):
        """龙虎榜机构成交明细"""
        return self._api.top_inst(trade_date=trade_date, ts_code=ts_code)

    # ============================================================
    # 基础数据
    # ============================================================

    def stock_basic(self, list_status: str = "L"):
        """股票基础信息"""
        return self._api.stock_basic(
            exchange="",
            list_status=list_status,
            fields="ts_code,symbol,name,area,industry,list_date",
        )

    def index_daily(self, ts_code: str = "000300.SH", start_date: str = "", end_date: str = ""):
        """指数日线（沪深300等）"""
        return self._api.index_daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

    # ============================================================
    # 公告/事件数据
    # ============================================================

    def anns_d(self, ts_code: str = "", start_date: str = "", end_date: str = ""):
        """上市公司公告"""
        return self._api.anns_d(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

    # ============================================================
    # 融资融券数据
    # ============================================================

    def margin_detail(self, trade_date: str = ""):
        """融资融券明细"""
        return self._api.margin_detail(trade_date=trade_date)

    # ============================================================
    # 解禁数据
    # ============================================================

    def share_float(self, ts_code: str = "", start_date: str = "", end_date: str = ""):
        """限售股解禁"""
        return self._api.share_float(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )
