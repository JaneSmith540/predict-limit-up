"""
Tushare 数据回测引擎 — 继承 vn.py BacktestingEngine

用 Tushare API 加载全市场日线数据，转换为 vn.py BarData 格式，
无需 vn.py 数据库，直接内存加载。

用法:
    from backtest.engine import TushareBacktestingEngine
    engine = TushareBacktestingEngine()
    engine.load_tushare_data("20250701", "20260804", warmup_days=20)
    engine.setup_market_params(capital=1_000_000)
    engine.add_strategy(LimitUpStrategy, setting)
    engine.strategy.model = trained_model
    engine.run_backtesting()
"""
from datetime import datetime, timedelta

from vnpy.trader.constant import Interval, Exchange
from vnpy.trader.object import BarData
from vnpy_portfoliostrategy.backtesting import BacktestingEngine

from utils import log


def ts_code_to_vt_symbol(ts_code: str) -> str:
    """Tushare 代码转 vn.py vt_symbol: 000001.SZ -> 000001.SZSE"""
    code, suffix = ts_code.split(".")
    if suffix == "SZ":
        return f"{code}.SZSE"
    elif suffix == "SH":
        return f"{code}.SSE"
    elif suffix == "BJ":
        return f"{code}.BSE"
    return ts_code


def parse_trade_date(date_str: str) -> datetime:
    """20250801 -> datetime(2025, 8, 1)"""
    return datetime.strptime(date_str, "%Y%m%d")


def ts_code_to_exchange(ts_code: str) -> Exchange:
    """Tushare 代码转交易所枚举"""
    _, suffix = ts_code.split(".")
    if suffix == "SZ":
        return Exchange.SZSE
    elif suffix == "SH":
        return Exchange.SSE
    elif suffix == "BJ":
        return Exchange.BSE
    raise ValueError(f"未知交易所后缀: {ts_code}")


class TushareBacktestingEngine(BacktestingEngine):
    """用 Tushare 全市场数据的 vn.py 回测引擎

    继承 vn.py BacktestingEngine，重写数据加载逻辑:
      - 不从 vn.py 数据库加载，而是直接从 Tushare API 获取
      - 将 Tushare daily 数据转为 vn.py BarData 格式
      - 自动发现全市场股票代码，填充 vt_symbols
    """

    def __init__(self) -> None:
        super().__init__()
        self.warmup_days: int = 20

    def load_tushare_data(
        self,
        start_date: str,
        end_date: str,
        warmup_days: int = 20,
    ) -> None:
        """
        从 Tushare 加载全市场日线数据为 vn.py BarData

        参数:
            start_date:  回测起始日 (YYYYMMDD)
            end_date:    回测结束日 (YYYYMMDD)
            warmup_days: 预热天数 (用于 MA 等滚动因子计算)
        """
        from data_fetch import data

        self.warmup_days = warmup_days

        self.output("开始从 Tushare 加载全市场数据...")

        # 清理上次加载的历史数据
        self.history_data.clear()
        self.dts.clear()

        # 计算预热期起始日（往前多取天数确保够用）
        start_dt = parse_trade_date(start_date)
        warmup_start_str = (start_dt - timedelta(days=warmup_days * 3)).strftime("%Y%m%d")

        # 获取交易日历（含预热期）
        all_cal = data.get_trade_cal(warmup_start_str, end_date)
        warmup_trade_days = [d for d in all_cal if d < start_date][-warmup_days:]
        bt_trade_days = [d for d in all_cal if start_date <= d <= end_date]
        all_days = warmup_trade_days + bt_trade_days

        self.output(f"预热天数: {len(warmup_trade_days)} | 回测天数: {len(bt_trade_days)}")

        # 记录回测起止时间 (供 vn.py 引擎使用)
        self.start = parse_trade_date(warmup_trade_days[0]) if warmup_trade_days else start_dt
        self.end = parse_trade_date(bt_trade_days[-1]) if bt_trade_days else parse_trade_date(end_date)
        self.interval = Interval.DAILY

        # 逐日加载全市场数据
        vt_symbols_set: set = set()

        for i, trade_date in enumerate(all_days):
            try:
                df = data.get_daily_all(trade_date)
            except Exception as e:
                self.output(f"跳过 {trade_date}: {e}")
                continue

            if df is None or len(df) == 0:
                continue

            dt = parse_trade_date(trade_date)
            self.dts.add(dt)

            # 遍历当日所有股票，转为 BarData
            for _, row in df.iterrows():
                ts_code = row.get("ts_code")
                if not ts_code or "." not in ts_code:
                    continue

                try:
                    exchange = ts_code_to_exchange(ts_code)
                except ValueError:
                    continue

                code = ts_code.split(".")[0]
                vt_symbol = f"{code}.{exchange.value}"
                vt_symbols_set.add(vt_symbol)

                bar = BarData(
                    symbol=code,
                    exchange=exchange,
                    datetime=dt,
                    interval=Interval.DAILY,
                    open_price=float(row["open"]),
                    high_price=float(row["high"]),
                    low_price=float(row["low"]),
                    close_price=float(row["close"]),
                    volume=float(row.get("vol", 0) or 0),
                    turnover=float(row.get("amount", 0) or 0),
                    gateway_name="BACKTESTING",
                )
                self.history_data[(dt, vt_symbol)] = bar

            if (i + 1) % 20 == 0:
                self.output(f"加载进度: {i + 1}/{len(all_days)} | 累计股票数: {len(vt_symbols_set)}")

        # 更新 vt_symbols (从数据中发现的全部股票)
        self.vt_symbols = sorted(vt_symbols_set)

        self.output(
            f"数据加载完成 | 总天数: {len(self.dts)} | 股票数: {len(self.vt_symbols)}"
        )

    def setup_market_params(
        self,
        capital: float = 1_000_000,
        rate: float = 0.0003,
        slippage: float = 0.0,
        size: float = 1.0,
        pricetick: float = 0.01,
        risk_free: float = 0.0,
        annual_days: int = 240,
    ) -> None:
        """
        为全市场股票设置统一的手续率、滑点、乘数、最小跳动

        在 load_tushare_data() 之后调用，因为需要知道全部 vt_symbols。
        """
        self.capital = capital
        self.risk_free = risk_free
        self.annual_days = annual_days

        self.rates = {s: rate for s in self.vt_symbols}
        self.slippages = {s: slippage for s in self.vt_symbols}
        self.sizes = {s: size for s in self.vt_symbols}
        self.priceticks = {s: pricetick for s in self.vt_symbols}

        self.output(
            f"参数设置完成 | 资金: {capital:,.0f} | 手续费率: {rate} | 股票数: {len(self.vt_symbols)}"
        )
