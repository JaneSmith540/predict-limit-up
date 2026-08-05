"""
股票行情数据获取与预处理
封装常用数据查询，提供 DataFrame 输出
"""

from typing import Optional

import pandas as pd

from data_fetch.tushare_client import TushareClient
from config.settings import config


class StockDataFetcher:
    """股票行情数据获取器"""

    def __init__(self):
        self.client = TushareClient()

    def get_daily(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        adj: str = "qfq",
    ) -> pd.DataFrame:
        """
        获取前复权日线数据

        Args:
            ts_code: 股票代码，如 "000001.SZ"
            start_date: 起始日期，如 "20200101"
            end_date: 结束日期
            adj: 复权方式 qfq前复权 / hfq后复权 / None不复权
        """
        df = self.client.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        if adj == "qfq":
            adj_df = self._api_adj(ts_code, start_date, end_date)
            # TODO: 合并复权因子
        df = df.sort_values("trade_date").reset_index(drop=True)
        return df

    def get_daily_basic(
        self, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """获取每日指标（换手率、PE、PB等）"""
        df = self.client.daily_basic(
            ts_code=ts_code, start_date=start_date, end_date=end_date
        )
        return df.sort_values("trade_date").reset_index(drop=True)

    def get_minute_data(
        self, ts_code: str, start_date: str, end_date: str, freq: str = "1min"
    ) -> pd.DataFrame:
        """获取分钟线数据"""
        df = self.client.stk_mins(ts_code, start_date, end_date, freq=freq)
        return df.sort_values("trade_time").reset_index(drop=True)

    def get_limit_up_list(self, trade_date: str) -> pd.DataFrame:
        """获取指定日期涨停板列表"""
        return self.client.limit_list_d(trade_date=trade_date)

    def get_limit_up_history(
        self, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """获取个股涨停历史"""
        df = self.client.limit_list_d(start_date=start_date, end_date=end_date)
        if ts_code:
            df = df[df["ts_code"] == ts_code]
        return df

    def get_money_flow(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取个股资金流向"""
        df = self.client.moneyflow(ts_code=ts_code, start_date=start_date, end_date=end_date)
        return df.sort_values("trade_date").reset_index(drop=True)

    def get_index_daily(
        self, ts_code: str = "000300.SH", start_date: str = "", end_date: str = ""
    ) -> pd.DataFrame:
        """获取指数日线（默认沪深300）"""
        df = self.client.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        return df.sort_values("trade_date").reset_index(drop=True)

    def get_all_stocks(self) -> pd.DataFrame:
        """获取全市场在上市股票列表"""
        return self.client.stock_basic()

    def _api_adj(self, ts_code: str, start_date: str, end_date: str):
        """获取复权因子（TODO）"""
        pass
