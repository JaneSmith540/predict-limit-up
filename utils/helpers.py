"""
通用工具函数
"""

from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd


def date_to_str(date: datetime, fmt: str = "%Y%m%d") -> str:
    """日期转字符串"""
    return date.strftime(fmt)


def str_to_date(date_str: str, fmt: str = "%Y%m%d") -> datetime:
    """字符串转日期"""
    return datetime.strptime(date_str, fmt)


def get_trade_dates(start_date: str, end_date: str, freq: str = "B") -> List[str]:
    """
    获取交易日列表（工作日，近似）
    TODO: 接入 Tushare 交易日历获取精确交易日
    """
    dates = pd.bdate_range(start=start_date, end=end_date)
    return [d.strftime("%Y%m%d") for d in dates]


def calc_limit_up_price(prev_close: float, pct: float = 0.10) -> float:
    """
    计算涨停价
    A股涨停规则: ST股5%，普通股10%，创业板/科创板20%
    """
    limit_price = prev_close * (1 + pct)
    # A股价格精度: 0.01元
    return round(limit_price, 2)


def calc_limit_down_price(prev_close: float, pct: float = 0.10) -> float:
    """计算跌停价"""
    limit_price = prev_close * (1 - pct)
    return round(limit_price, 2)


def is_limit_up(close: float, prev_close: float, pct: float = 0.10) -> bool:
    """判断是否涨停"""
    limit_price = calc_limit_up_price(prev_close, pct)
    return abs(close - limit_price) < 0.01


def is_st_stock(ts_code: str) -> bool:
    """判断是否ST股（简单判断，TODO: 接入实时数据）"""
    return "ST" in ts_code or "*ST" in ts_code


def get_board_type(ts_code: str) -> str:
    """
    获取板块类型
    返回: main(主板) / star(科创板) / gem(创业板) / bse(北交所)
    """
    if ts_code.startswith("688"):
        return "star"
    elif ts_code.startswith("300") or ts_code.startswith("301"):
        return "gem"
    elif ts_code.startswith("8"):
        return "bse"
    else:
        return "main"


def get_limit_pct(ts_code: str) -> float:
    """获取涨跌停幅度"""
    if is_st_stock(ts_code):
        return 0.05
    board = get_board_type(ts_code)
    if board in ("star", "gem"):
        return 0.20
    return 0.10


def format_volume(volume: int) -> str:
    """格式化成交量"""
    if volume >= 100000000:
        return f"{volume / 100000000:.2f}亿"
    elif volume >= 10000:
        return f"{volume / 10000:.2f}万"
    return str(volume)


def format_amount(amount: float) -> str:
    """格式化成交额"""
    if amount >= 100000000:
        return f"{amount / 100000000:.2f}亿"
    elif amount >= 10000:
        return f"{amount / 10000:.2f}万"
    return f"{amount:.2f}"
