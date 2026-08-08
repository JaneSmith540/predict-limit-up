"""全市场回测引擎（vn.py 版）— 滚动重训架构"""
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

from vnpy.trader.constant import Direction

from utils import get_config, log
from data_fetch import data
from factors import compute_factors, get_factor_columns
from model import LimitUpModel, ExitModel

from backtest.engine import TushareBacktestingEngine
from strategies.limit_up_strategy import LimitUpStrategy

RESULT_DIR = Path(__file__).parent.parent / "logs"


def run_backtest(ts_code=None):
    if ts_code:
        return _run_single(ts_code)
    else:
        return _run_market()


def _run_market():
    bt_start = get_config("backtest.start_date", "20250801")
    bt_end = get_config("backtest.end_date", "20260804")
    train_start = get_config("backtest.train_start_date", "20240101")
    daily_pick = get_config("backtest.daily_pick", 2)
    max_positions = get_config("backtest.max_positions", 2)
    initial_capital = get_config("trading.initial_capital", 1_000_000)
    position_size = get_config("trading.position_size", 0.50)
    stop_loss = get_config("trading.stop_loss", -0.04)
    take_profit = get_config("trading.take_profit", 0.10)
    max_holding_days = get_config("trading.max_holding_days", 3)
    warmup_days = get_config("backtest.warmup_days", 30)

    log.info("=" * 60)
    log.info("全市场涨停预测回测（vn.py 引擎 + 滚动重训）")
    log.info("  回测期间: " + bt_start + " ~ " + bt_end)
    log.info("  每日选股: " + str(daily_pick) + " | 最大持仓数: " + str(max_positions))
    log.info("=" * 60)

    # --- 1. 滚动训练多个模型 ---
    models_with_dates, exit_model = _train_models_rolling(train_start, bt_start, bt_end)

    # --- 2. 创建 vn.py 回测引擎 ---
    engine = TushareBacktestingEngine()

    # --- 3. 加载全市场数据 ---
    engine.load_tushare_data(bt_start, bt_end, warmup_days=warmup_days)

    # --- 4. 设置市场参数 ---
    engine.setup_market_params(capital=initial_capital)

    # --- 5. 添加策略 ---
    min_prob = get_config("model.predict_threshold", 0.40)
    setting = {
        "daily_pick": daily_pick,
        "max_positions": max_positions,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "max_holding_days": max_holding_days,
        "position_size": position_size,
        "initial_capital": initial_capital,
        "min_prob": min_prob,
    }
    engine.add_strategy(LimitUpStrategy, setting)

    # --- 6. 注入多模型 ---
    engine.strategy.models_with_dates = models_with_dates
    engine.strategy.exit_model = exit_model
    log.info("已注入 " + str(len(models_with_dates)) + " 个滚动模型到策略")

    # --- 7. 运行回测 ---
    log.info("开始 vn.py 回测...")
    engine.run_backtesting()

    # --- 8. 计算盈亏 ---
    engine.calculate_result()

    # --- 9. 统计指标 ---
    stats = engine.calculate_statistics()

    # --- 10. 输出 ---
    _save_trades(engine, "全市场")
    _plot_equity_curve(engine, "全市场", initial_capital)

    # --- 11. 可视化报告 ---
    try:
        from visualization.report import generate_market_report
        generate_market_report(
            engine, statistics=stats, name="全市场",
            parameters={
                "backtest_start": bt_start, "backtest_end": bt_end,
                "train_start": train_start, "daily_pick": daily_pick,
                "max_positions": max_positions, "initial_capital": initial_capital,
                "position_size": position_size, "stop_loss": stop_loss,
                "take_profit": take_profit, "max_holding_days": max_holding_days,
            },
        )
    except Exception as exc:
        log.exception("报告生成失败: " + str(exc))

    return engine


def _train_models_rolling(train_start, bt_start, bt_end):
    """滚动训练多个模型，每个模型对应一段时间段"""

    segments = [
        (bt_start,   "20260101", train_start, bt_start),
        ("20260101", "20260501", "20240601",  "20260101"),
        ("20260501", bt_end,     "20250101",  "20260501"),
    ]

    models_with_dates = []
    last_train_df = None

    for i, (seg_start, seg_end, tr_start, tr_end) in enumerate(segments):
        log.info("=" * 50)
        log.info("滚动训练 模型" + str(i+1) + "/" + str(len(segments)))
        log.info("  回测段: " + seg_start + " ~ " + seg_end)
        log.info("  训练数据: " + tr_start + " ~ " + tr_end)

        limit_stocks = data.get_limit_list_range(tr_start, tr_end)
        train_stock_pool = limit_stocks["ts_code"].unique().tolist()
        log.info("  训练期涨停股票数: " + str(len(train_stock_pool)))

        train_data = []
        for j, code in enumerate(train_stock_pool):
            try:
                df = data.get_daily(code, tr_start, tr_end)
                df = compute_factors(df)
                train_data.append(df)
            except Exception:
                pass
            if (j + 1) % 200 == 0:
                log.info("    下载进度: " + str(j + 1) + "/" + str(len(train_stock_pool)))

        if not train_data:
            log.warning("  模型" + str(i+1) + " 无训练数据，跳过")
            continue

        train_df = pd.concat(train_data, ignore_index=True)
        last_train_df = train_df
        log.info("  训练数据总计: " + str(len(train_df)) + " 条")

        entry_model = LimitUpModel()
        entry_model.train(train_df)

        models_with_dates.append({
            "start": seg_start,
            "end": seg_end,
            "model": entry_model,
        })

    exit_threshold = get_config("model.exit_threshold", 0.0)
    exit_model = ExitModel()
    if exit_threshold > 0 and last_train_df is not None:
        exit_model.train(last_train_df)
    else:
        log.info("卖出模型已禁用(exit_threshold<=0)，跳过训练")

    return models_with_dates, exit_model


def _save_trades(engine, name):
    trades = engine.get_all_trades()
    if not trades:
        log.info("无交易记录")
        return
    records = []
    for t in trades:
        records.append({
            "vt_symbol": t.vt_symbol,
            "direction": t.direction.value,
            "offset": t.offset.value,
            "price": t.price,
            "volume": t.volume,
            "datetime": str(t.datetime),
        })
    df = pd.DataFrame(records)
    RESULT_DIR.mkdir(exist_ok=True)
    csv_path = RESULT_DIR / ("trades_" + name + ".csv")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    log.info("交易记录已保存: " + str(csv_path) + " (" + str(len(records)) + " 笔)")


def _plot_equity_curve(engine, name, initial_capital):
    if engine.daily_df is None or len(engine.daily_df) == 0:
        log.info("无数据，无法绘制收益曲线")
        return
    df = engine.daily_df.copy()
    df["balance"] = df["net_pnl"].cumsum() + initial_capital
    plt.figure(figsize=(12, 6))
    plt.plot(df.index, df["balance"].values, label="Equity", color="blue")
    plt.axhline(y=initial_capital, color="gray", linestyle="--", label="Initial Capital")
    plt.title("Equity Curve - " + name)
    plt.xlabel("Date")
    plt.ylabel("Capital")
    plt.legend()
    plt.tight_layout()
    RESULT_DIR.mkdir(exist_ok=True)
    png_path = RESULT_DIR / ("equity_" + name + ".png")
    plt.savefig(png_path, dpi=150)
    plt.close()
    log.info("收益曲线已保存: " + str(png_path))


def _run_single(ts_code):
    """单股回测（兼容旧版）"""
    import numpy as np
    from strategies import Strategy
    bt_start = get_config("backtest.start_date", "20250801")
    bt_end = get_config("backtest.end_date", "20260804")
    train_start = get_config("backtest.train_start_date", "20240101")
    log.info("=== 单股回测: " + ts_code + " ===")
    df = data.get_daily(ts_code, train_start, bt_end)
    df = compute_factors(df)
    train_df = df[df["trade_date"] < bt_start].copy()
    test_df = df[df["trade_date"] >= bt_start].copy()
    model = LimitUpModel()
    model.train(train_df)
    test_df = test_df.copy()
    test_df["prob"] = model.predict(test_df)
    threshold = get_config("model.predict_threshold", 0.05)
    strategy = Strategy()
    capital = strategy.initial_capital
    position = None
    trades = []
    equity_curve = []
    pending_buy = False
    pending_sell = False
    sell_reason = ""
    for i in range(len(test_df)):
        row = test_df.iloc[i]
        current_price = row["close"]
        current_date = row["trade_date"]
        prob = row["prob"]
        if pending_sell and position is not None:
            sell_price = row["open"]
            pnl = (sell_price - position["cost_price"]) / position["cost_price"]
            capital += position["shares"] * sell_price
            trades.append({"buy_date": position["buy_date"], "sell_date": current_date,
                          "buy_price": position["cost_price"], "sell_price": sell_price,
                          "shares": position["shares"], "pnl": pnl, "reason": sell_reason})
            position = None
            pending_sell = False
        if pending_buy and position is None:
            buy_price = row["open"]
            buy_amount = capital * strategy.position_size
            shares = int(buy_amount / buy_price / 100) * 100
            if shares > 0:
                capital -= shares * buy_price
                position = {"shares": shares, "cost_price": buy_price,
                           "buy_date": current_date, "holding_days": 0}
            pending_buy = False
        if position is not None:
            position["holding_days"] += 1
            should_sell, reason = strategy.should_sell(position, current_price)
            if should_sell:
                pending_sell = True
                sell_reason = reason
        if position is None and strategy.should_buy(prob, threshold):
            pending_buy = True
        position_value = position["shares"] * current_price if position else 0
        equity = capital + position_value
        equity_curve.append({"date": current_date, "equity": equity})
    if position is not None:
        last_price = test_df.iloc[-1]["close"]
        pnl = (last_price - position["cost_price"]) / position["cost_price"]
        capital += position["shares"] * last_price
        trades.append({"buy_date": position["buy_date"], "sell_date": test_df.iloc[-1]["trade_date"],
                      "buy_price": position["cost_price"], "sell_price": last_price,
                      "shares": position["shares"], "pnl": pnl, "reason": "回测结束平仓"})
    _print_single_results(ts_code, trades, equity_curve, strategy.initial_capital)
    _plot_single_equity(ts_code, equity_curve, strategy.initial_capital)
    return trades, equity_curve


def _print_single_results(name, trades, equity_curve, initial_capital):
    if not trades:
        log.info("无交易记录")
        return
    df_trades = pd.DataFrame(trades)
    final_equity = equity_curve[-1]["equity"] if equity_curve else initial_capital
    total_return = (final_equity - initial_capital) / initial_capital
    win_rate = (df_trades["pnl"] > 0).mean()
    log.info("=" * 60)
    log.info("单股回测结果: " + name)
    log.info("=" * 60)
    log.info("总交易次数: " + str(len(trades)))
    log.info("胜率: " + format(win_rate, ".1%"))
    log.info("总收益率: " + format(total_return, ".1%"))
    log.info("=" * 60)
    RESULT_DIR.mkdir(exist_ok=True)
    df_trades.to_csv(RESULT_DIR / ("trades_" + name + ".csv"), index=False, encoding="utf-8-sig")


def _plot_single_equity(name, equity_curve, initial_capital):
    if not equity_curve:
        return
    df = pd.DataFrame(equity_curve)
    plt.figure(figsize=(12, 6))
    plt.plot(df["equity"].values, label="Equity", color="blue")
    plt.axhline(y=initial_capital, color="gray", linestyle="--", label="Initial Capital")
    plt.title("Equity Curve - " + name)
    plt.xlabel("Days")
    plt.ylabel("Capital")
    plt.legend()
    plt.tight_layout()
    RESULT_DIR.mkdir(exist_ok=True)
    plt.savefig(RESULT_DIR / ("equity_" + name + ".png"), dpi=150)
    plt.close()
