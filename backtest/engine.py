from datetime import datetime, date, timedelta
from collections import defaultdict

import numpy as np
import pandas as pd
from vnpy.trader.constant import Direction, Offset, Interval, Status, Exchange
from vnpy.trader.object import BarData, OrderData, TradeData
from vnpy_portfoliostrategy.backtesting import BacktestingEngine

from utils import get_config, log
from data_fetch import data


EXCHANGE_MAP = {'SZ': Exchange.SZSE, 'SH': Exchange.SSE, 'BJ': Exchange.BSE}

def _to_vnpy_symbol(ts_code):
    parts = ts_code.split('.')
    symbol = parts[0]
    suffix = parts[1] if len(parts) > 1 else 'SH'
    ex = EXCHANGE_MAP.get(suffix, Exchange.SSE)
    return symbol + '.' + ex.value


class TushareBacktestingEngine(BacktestingEngine):
    """BacktestingEngine that loads data from Tushare instead of database"""

    def load_tushare_data(self, start_date, end_date, warmup_days=30):
        log.info('Loading Tushare data: ' + start_date + ' ~ ' + end_date)

        trade_cal = data.get_trade_cal(start_date, end_date)
        log.info('Trade days: ' + str(len(trade_cal)))

        limit_stocks = data.get_limit_list_range(start_date, end_date)
        ts_codes = sorted(limit_stocks['ts_code'].unique().tolist())
        log.info('Stock universe: ' + str(len(ts_codes)) + ' stocks')

        warmup_start = (datetime.strptime(start_date, '%Y%m%d') - timedelta(days=warmup_days * 2)).strftime('%Y%m%d')

        self.history_data = {}
        self.dts = set()
        vnpy_symbols = []

        for i, ts_code in enumerate(ts_codes):
            try:
                df = data.get_daily(ts_code, warmup_start, end_date)
                if df is None or len(df) == 0:
                    continue
                parts = ts_code.split('.')
                symbol = parts[0]
                suffix = parts[1] if len(parts) > 1 else 'SH'
                ex = EXCHANGE_MAP.get(suffix, Exchange.SSE)
                vt_sym = symbol + '.' + ex.value
                vnpy_symbols.append(vt_sym)
                for _, row in df.iterrows():
                    dt = datetime.strptime(str(row['trade_date']), '%Y%m%d')
                    bar = BarData(
                        gateway_name='BACKTESTING',
                        symbol=symbol,
                        exchange=ex,
                        datetime=dt,
                        interval=Interval.DAILY,
                        open_price=float(row['open']),
                        high_price=float(row['high']),
                        low_price=float(row['low']),
                        close_price=float(row['close']),
                        volume=float(row['vol']),
                    )
                    self.history_data[(dt, vt_sym)] = bar
                    self.dts.add(dt)
            except Exception as e:
                log.debug('Skip ' + ts_code + ': ' + str(e))
            if (i + 1) % 200 == 0:
                log.info('  Loading: ' + str(i + 1) + '/' + str(len(ts_codes)))

        self.vt_symbols = vnpy_symbols
        log.info('Data loaded: ' + str(len(self.history_data)) + ' bars, ' + str(len(self.dts)) + ' days')

    def setup_market_params(self, capital=1000000):
        rate = get_config('vnpy.rate', 0.0003)
        slippage = get_config('vnpy.slippage', 0.0)
        size = get_config('vnpy.size', 1.0)
        pricetick = get_config('vnpy.pricetick', 0.01)
        risk_free = get_config('vnpy.risk_free', 0.0)
        annual_days = get_config('vnpy.annual_days', 240)

        bt_start = get_config('backtest.start_date', '20250801')
        bt_end = get_config('backtest.end_date', '20260804')

        rates = {s: rate for s in self.vt_symbols}
        slippages = {s: slippage for s in self.vt_symbols}
        sizes = {s: size for s in self.vt_symbols}
        priceticks = {s: pricetick for s in self.vt_symbols}

        self.set_parameters(
            vt_symbols=self.vt_symbols,
            interval=Interval.DAILY,
            start=datetime.strptime(bt_start, '%Y%m%d'),
            end=datetime.strptime(bt_end, '%Y%m%d'),
            rates=rates,
            slippages=slippages,
            sizes=sizes,
            priceticks=priceticks,
            capital=capital,
            risk_free=risk_free,
            annual_days=annual_days,
        )
        log.info('Market params set: rate=' + str(rate) + ' capital=' + str(capital))
