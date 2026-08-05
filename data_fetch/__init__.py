"""
数据获取模块 — 封装 Tushare API

使用方法:
    from data_fetch import data
    df = data.get_daily("000001.SZ", "20240101", "20240601")
"""
import tushare as ts
import pandas as pd
from utils import TUSHARE_TOKEN, get_config, log


class TushareAPI:
    """Tushare API 封装"""

    def __init__(self):
        if not TUSHARE_TOKEN:
            raise ValueError("TUSHARE_TOKEN 未设置，请创建 .env 文件并填入 token")
        ts.set_token(TUSHARE_TOKEN)
        self.api = ts.pro_api()
        log.info("Tushare API 初始化成功")

    def get_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取日线行情（前复权）"""
        df = self.api.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
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


# 全局实例
data = TushareAPI()
