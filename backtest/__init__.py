"""
全市场回测引擎（vn.py 版）— 双模型架构

流程:
  1. 训练 RF 买入模型 + RF 卖出模型
  2. 用 TushareBacktestingEngine 加载全市场数据
  3. 注入双模型到 LimitUpStrategy
  4. 运行 vn.py 回测引擎
  5. 输出统计指标和交易记录
"""
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


def run_backtest(ts_code: str = None):
    if ts_code:
        return _run_single(ts_code)
    else:
        return _run_market()


def _run_market():
    """全市场回测（vn.py 引擎）"""
    bt_start = get_config("backtest.start_date", "20250801")
    bt_end = get_config("backtest.end_date", "20260804")
    train_start = get_config("backtest.train_start_date", "20240101")
    daily_pick = get_config("backtest.daily_pick", 2)
    max_positions = get_config("backtest.max_positions", 2)
    initial_capital = get_config("trading.initial_capital", 1_000_000)
    position_size = get_config("trading.position_size", 0.35)
    stop_loss = get_config("trading.stop_loss", -0.04)
    take_profit = get_config("trading.take_profit", 0.08)
    max_holding_days = get_config("trading.max_holding_days", 3)
    warmup_days = get_config("backtest.warmup_days", 30)

    log.info("=" * 60)
    log.info("全市场涨停预测回测（vn.py 引擎 + 双RF模型）")
    log.info(f"  训练数据: {train_start} ~ {bt_start}")
    log.info(f"  回测期间: {bt_start} ~ {bt_end}")
    log.info(f"  每日选股: {daily_pick} | 最大持仓数: {max_positions}")
    log.info(f"  交易时序: t日收盘信号 -> t+1日开盘成交")
    log.info("=" * 60)

    # --- 1. 训练双模型 ---
    entry_model, exit_model = _train_models(train_start, bt_start)

    # --- 2. 创建 vn.py 回测引擎 ---
    engine = TushareBacktestingEngine()

    # --- 3. 加载全市场数据 ---
    engine.load_tushare_data(bt_start, bt_end, warmup_days=warmup_days)

    # --- 4. 设置市场参数 ---
    engine.setup_market_params(capital=initial_capital)

    # --- 5. 添加策略 ---
    min_prob = get_config("model.predict_threshold", 0.45)
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

    # --- 6. 注入双模型 ---
    engine.strategy.model = entry_model
    engine.strategy.exit_model = exit_model
    log.info("买入模型 + 卖出模型 已注入策略")

    # --- 6.5 市场趋势过滤（可选）---
    market_filter_enabled = get_config("trading.market_filter", False)
    if market_filter_enabled:
        market_ma = get_config("trading.market_ma", 10)
        try:
            index_df = data.get_index_daily("000300.SH", bt_start, bt_end)
            index_df = index_df.sort_values("trade_date").reset_index(drop=True)
            index_df["ma"] = index_df["close"].rolling(market_ma).mean()
            index_df["above_ma"] = index_df["close"] > index_df["ma"]
            trade_days = set(index_df[index_df["above_ma"]]["trade_date"].tolist())
            engine.strategy.market_trade_days = trade_days
            log.info(f"市场趋势过滤: {len(trade_days)}/{len(index_df)} 天允许交易")
        except Exception as e:
            log.warning(f"市场趋势过滤加载失败: {e}")

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

    # --- 11. 生成独立静态可视化报告（不参与交易逻辑） ---
    try:
        from visualization import generate_market_report

        report_dir = generate_market_report(
            engine,
            statistics=stats,
            name="全市场",
            parameters={
                "backtest_start": bt_start,
                "backtest_end": bt_end,
                "train_start": train_start,
                "daily_pick": daily_pick,
                "max_positions": max_positions,
                "initial_capital": initial_capital,
                "position_size": position_size,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "max_holding_days": max_holding_days,
                "annual_days": getattr(engine, "annual_days", 240),
            },
        )
        log.info(f"静态可视化报告已生成: {report_dir}")
    except Exception as exc:
        log.exception(f"静态可视化报告生成失败（不影响回测结果）: {exc}")

    return engine


def _train_models(train_start: str, bt_start: str):
    """训练买入模型 + 卖出模型"""
    log.info("收集训练用涨停股票...")
    limit_stocks = data.get_limit_list_range(train_start, bt_start)
    train_stock_pool = limit_stocks["ts_code"].unique().tolist()
    log.info(f"训练期涨停股票数: {len(train_stock_pool)}")

    log.info("下载训练数据...")
    train_data = []
    for i, code in enumerate(train_stock_pool):
        try:
            df = data.get_daily(code, train_start, bt_start)
            df = compute_factors(df)
            train_data.append(df)
        except Exception as e:
            log.debug(f"跳过 {code}: {e}")
        if (i + 1) % 50 == 0:
            log.info(f"  下载进度: {i + 1}/{len(train_stock_pool)}")

    train_df = pd.concat(train_data, ignore_index=True)
    log.info(f"训练数据总计: {len(train_df)} 条")

    # 训练买入模型
    log.info("=" * 40)
    entry_model = LimitUpModel()
    entry_model.train(train_df)

    # 训练卖出模型（如果启用）
    exit_threshold = get_config("model.exit_threshold", 0.0)
    exit_model = ExitModel()
    if exit_threshold > 0:
        log.info("=" * 40)
        exit_model.train(train_df)
    else:
        log.info("卖出模型已禁用(exit_threshold<=0)，跳过训练")

    return entry_model, exit_model


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
    csv_path = RESULT_DIR / f"trades_{name}.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    log.info(f"交易记录已保存: {csv_path} ({len(records)} 笔)")


def _plot_equity_curve(engine, name, initial_capital):
    if engine.daily_df is None or len(engine.daily_df) == 0:
        log.info("无数据，无法绘制收益曲线")
        return

    df = engine.daily_df.copy()
    df["balance"] = df["net_pnl"].cumsum() + initial_capital

    plt.figure(figsize=(12, 6))
    plt.plot(df.index, df["balance"].values, label="Equity", color="blue")
    plt.axhline(y=initial_capital, color="gray", linestyle="--", label="Initial Capital")
    plt.title(f"Equity Curve - {name}")
    plt.xlabel("Date")
    plt.ylabel("Capital")
    plt.legend()
    plt.tight_layout()

    RESULT_DIR.mkdir(exist_ok=True)
    png_path = RESULT_DIR / f"equity_{name}.png"
    plt.savefig(png_path, dpi=150)
    plt.close()
    log.info(f"收益曲线已保存: {png_path}")


# ============================================================
# 单股回测（兼容旧版）
# ============================================================

def _run_single(ts_code: str):
    """单股回测（兼容旧版）"""
    import numpy as np
    from strategy import Strategy

    bt_start = get_config("backtest.start_date", "20250801")
    bt_end = get_config("backtest.end_date", "20260804")
    train_start = get_config("backtest.train_start_date", "20240101")

    log.info(f"=== 单股回测: {ts_code} ===")

    log.info("下载日线数据...")
    df = data.get_daily(ts_code, train_start, bt_end)
    log.info(f"获取 {len(df)} 条数据")

    log.info("计算因子...")
    df = compute_factors(df)

    train_df = df[df["trade_date"] < bt_start].copy()
    test_df = df[df["trade_date"] >= bt_start].copy()
    log.info(f"训练集: {len(train_df)} 条 | 回测集: {len(test_df)} 条")

    log.info("训练模型...")
    model = LimitUpModel()
    metrics = model.train(train_df)
    log.info(f"训练完成 | 准确率: {metrics['accuracy']:.2%}")

    log.info("开始逐日回测...")
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
            trades.append({
                "buy_date": position["buy_date"],
                "sell_date": current_date,
                "buy_price": position["cost_price"],
                "sell_price": sell_price,
                "shares": position["shares"],
                "pnl": pnl,
                "reason": sell_reason,
            })
            position = None
            pending_sell = False

        if pending_buy and position is None:
            buy_price = row["open"]
            buy_amount = capital * strategy.position_size
            shares = int(buy_amount / buy_price / 100) * 100
            if shares > 0:
                capital -= shares * buy_price
                position = {
                    "shares": shares,
                    "cost_price": buy_price,
                    "buy_date": current_date,
                    "holding_days": 0,
                }
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
        trades.append({
            "buy_date": position["buy_date"],
            "sell_date": test_df.iloc[-1]["trade_date"],
            "buy_price": position["cost_price"],
            "sell_price": last_price,
            "shares": position["shares"],
            "pnl": pnl,
            "reason": "回测结束平仓",
        })
        position = None

    _print_single_results(ts_code, trades, equity_curve, strategy.initial_capital)
    _plot_single_equity(ts_code, equity_curve, strategy.initial_capital)
    try:
        from visualization import generate_single_report

        report_dir = generate_single_report(
            ts_code=ts_code,
            trades=trades,
            equity_curve=equity_curve,
            initial_capital=strategy.initial_capital,
            parameters={
                "backtest_start": bt_start,
                "backtest_end": bt_end,
                "train_start": train_start,
                "initial_capital": strategy.initial_capital,
                "position_size": strategy.position_size,
                "stop_loss": strategy.stop_loss,
                "take_profit": strategy.take_profit,
                "max_holding_days": strategy.max_holding_days,
            },
        )
        log.info(f"静态可视化报告已生成: {report_dir}")
    except Exception as exc:
        log.exception(f"静态可视化报告生成失败（不影响回测结果）: {exc}")
    return trades, equity_curve


def _print_single_results(name, trades, equity_curve, initial_capital):
    if not trades:
        log.info("无交易记录")
        return

    df_trades = pd.DataFrame(trades)
    final_equity = equity_curve[-1]["equity"] if equity_curve else initial_capital
    total_return = (final_equity - initial_capital) / initial_capital
    win_rate = (df_trades["pnl"] > 0).mean()
    avg_win = df_trades.loc[df_trades["pnl"] > 0, "pnl"].mean() if (df_trades["pnl"] > 0).any() else 0
    avg_loss = df_trades.loc[df_trades["pnl"] <= 0, "pnl"].mean() if (df_trades["pnl"] <= 0).any() else 0
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

    eq = pd.Series([e["equity"] for e in equity_curve])
    peak = eq.cummax()
    drawdown = (eq - peak) / peak
    max_drawdown = drawdown.min()

    log.info("=" * 60)
    log.info(f"单股回测结果: {name}")
    log.info("=" * 60)
    log.info(f"总交易次数: {len(trades)}")
    log.info(f"胜率: {win_rate:.1%}")
    if avg_win:
        log.info(f"平均盈利: {avg_win:.1%}")
    if avg_loss:
        log.info(f"平均亏损: {avg_loss:.1%}")
    log.info(f"盈亏比: {profit_factor:.2f}")
    log.info(f"总收益率: {total_return:.1%}")
    log.info(f"最大回撤: {max_drawdown:.1%}")
    log.info(f"最终资金: {final_equity:,.0f}")
    log.info("=" * 60)

    RESULT_DIR.mkdir(exist_ok=True)
    df_trades.to_csv(RESULT_DIR / f"trades_{name}.csv", index=False, encoding="utf-8-sig")


def _plot_single_equity(name, equity_curve, initial_capital):
    if not equity_curve:
        return

    df = pd.DataFrame(equity_curve)
    plt.figure(figsize=(12, 6))
    plt.plot(df["equity"].values, label="Equity", color="blue")
    plt.axhline(y=initial_capital, color="gray", linestyle="--", label="Initial Capital")
    plt.title(f"Equity Curve - {name}")
    plt.xlabel("Days")
    plt.ylabel("Capital")
    plt.legend()
    plt.tight_layout()
    RESULT_DIR.mkdir(exist_ok=True)
    plt.savefig(RESULT_DIR / f"equity_{name}.png", dpi=150)
    plt.close()
