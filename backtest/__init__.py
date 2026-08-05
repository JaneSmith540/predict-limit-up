"""
全市场回测引擎

流程:
  1. 获取回测期间的交易日历
  2. 收集训练用的涨停样本（训练期内有过涨停的股票历史数据）
  3. 训练多元线性回归模型
  4. 逐日回测: 每天全市场扫描 → 模型预测 → 选 top N 买入 → 持仓检查 → 卖出
  5. 输出收益曲线和统计指标

用法:
  python -m backtest run              # 全市场回测（最近1年）
  python -m backtest run 000001.SZ     # 单股回测（兼容旧版）
"""
import sys
import time
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

from utils import get_config, log
from data_fetch import data
from factors import compute_factors, get_factor_columns
from model import LimitUpModel
from strategy import Strategy

RESULT_DIR = Path(__file__).parent.parent / "logs"


def run_backtest(ts_code: str = None):
    """
    回测入口
    - 不传 ts_code: 全市场回测
    - 传 ts_code: 单股回测
    """
    if ts_code:
        return _run_single(ts_code)
    else:
        return _run_market()


def _run_market():
    """全市场回测"""
    bt_start = get_config("backtest.start_date", "20250801")
    bt_end = get_config("backtest.end_date", "20260804")
    train_start = get_config("backtest.train_start_date", "20240101")
    daily_pick = get_config("backtest.daily_pick", 3)
    max_positions = get_config("backtest.max_positions", 3)

    log.info("=" * 60)
    log.info("全市场涨停预测回测")
    log.info(f"  训练数据: {train_start} ~ {bt_start}")
    log.info(f"  回测期间: {bt_start} ~ {bt_end}")
    log.info(f"  每日选股: {daily_pick} | 最大持仓数: {max_positions}")
    log.info("=" * 60)

    # 1. 获取交易日历
    log.info("获取交易日历...")
    trade_days = data.get_trade_cal(bt_start, bt_end)
    log.info(f"回测交易日数: {len(trade_days)}")

    # 2. 收集训练数据：取训练期内有过涨停的股票
    log.info("收集训练用涨停股票...")
    limit_stocks = data.get_limit_list_range(train_start, bt_start)
    train_stock_pool = limit_stocks["ts_code"].unique().tolist()
    log.info(f"训练期涨停股票数: {len(train_stock_pool)}")

    # 3. 下载这些股票的训练数据，合并成大表
    log.info("下载训练数据（这可能需要几分钟）...")
    train_data = []
    for i, code in enumerate(train_stock_pool):
        try:
            df = data.get_daily(code, train_start, bt_start)
            df = compute_factors(df)
            df["ts_code"] = code
            train_data.append(df)
        except Exception as e:
            log.debug(f"跳过 {code}: {e}")
        if (i + 1) % 50 == 0:
            log.info(f"  下载进度: {i+1}/{len(train_stock_pool)}")
    train_df = pd.concat(train_data, ignore_index=True)
    log.info(f"训练数据总计: {len(train_df)} 条")

    # 4. 训练模型
    log.info("训练模型...")
    model = LimitUpModel()
    metrics = model.train(train_df)
    log.info(f"训练完成 | 准确率: {metrics['accuracy']:.2%}")

    # 5. 逐日回测
    log.info("开始全市场逐日回测...")
    strategy = Strategy()
    capital = strategy.initial_capital
    positions = {}  # {ts_code: position_dict}
    trades = []
    equity_curve = []

    for day_idx, trade_date in enumerate(trade_days):
        # 5a. 获取当天全市场行情
        try:
            market_data = data.get_daily_all(trade_date)
        except Exception as e:
            log.warning(f"获取{trade_date}数据失败: {e}")
            continue

        if market_data is None or len(market_data) == 0:
            continue

        # 5b. 计算因子（全市场）
        market_data = compute_factors(market_data)

        # 5c. 检查持仓 → 是否卖出
        to_remove = []
        for code, pos in positions.items():
            stock_row = market_data[market_data["ts_code"] == code]
            if len(stock_row) == 0:
                pos["holding_days"] += 1
                continue
            current_price = stock_row.iloc[0]["close"]
            should_sell, reason = strategy.should_sell(pos, current_price)
            if should_sell:
                pnl = (current_price - pos["cost_price"]) / pos["cost_price"]
                capital += pos["shares"] * current_price
                trades.append({
                    "ts_code": code,
                    "buy_date": pos["buy_date"],
                    "sell_date": trade_date,
                    "buy_price": pos["cost_price"],
                    "sell_price": current_price,
                    "shares": pos["shares"],
                    "pnl": pnl,
                    "reason": reason,
                })
                log.info(f"[{trade_date}] 卖出 {code} @ {current_price:.2f} | {reason} | {pnl:.1%}")
                to_remove.append(code)
            else:
                pos["holding_days"] += 1
        for code in to_remove:
            del positions[code]

        # 5d. 模型预测全市场
        valid_data = market_data.dropna(subset=get_factor_columns())
        if len(valid_data) == 0:
            continue
        probs = model.predict(valid_data)
        valid_data = valid_data.copy()
        valid_data["prob"] = probs

        # 5e. 选预测概率最高的 N 只
        top_n = valid_data.nlargest(daily_pick, "prob")

        # 5f. 买入（有空位才买）
        slots = max_positions - len(positions)
        if slots <= 0:
            pass
        else:
            for _, row in top_n.head(slots).iterrows():
                code = row["ts_code"]
                if code in positions:
                    continue
                current_price = row["close"]
                buy_amount = capital * strategy.position_size
                shares = int(buy_amount / current_price / 100) * 100
                if shares < 100:
                    continue
                capital -= shares * current_price
                positions[code] = {
                    "shares": shares,
                    "cost_price": current_price,
                    "buy_date": trade_date,
                    "holding_days": 0,
                }
                log.info(f"[{trade_date}] 买入 {code} @ {current_price:.2f} | {shares}股 | 概率: {row['prob']:.4f}")

        # 5g. 记录每日净值
        position_value = sum(
            p["shares"] * market_data[market_data["ts_code"] == c].iloc[0]["close"]
            for c, p in positions.items()
            if len(market_data[market_data["ts_code"] == c]) > 0
        )
        equity = capital + position_value
        equity_curve.append({"date": trade_date, "equity": equity})

        if (day_idx + 1) % 20 == 0:
            log.info(f"  回测进度: {day_idx+1}/{len(trade_days)} | 净值: {equity:,.0f} | 持仓: {len(positions)}")

    # 6. 回测结束，平仓所有持仓
    last_date = trade_days[-1]
    last_data = data.get_daily_all(last_date)
    for code, pos in list(positions.items()):
        stock_row = last_data[last_data["ts_code"] == code]
        if len(stock_row) > 0:
            last_price = stock_row.iloc[0]["close"]
            pnl = (last_price - pos["cost_price"]) / pos["cost_price"]
            capital += pos["shares"] * last_price
            trades.append({
                "ts_code": code,
                "buy_date": pos["buy_date"],
                "sell_date": last_date,
                "buy_price": pos["cost_price"],
                "sell_price": last_price,
                "shares": pos["shares"],
                "pnl": pnl,
                "reason": "回测结束平仓",
            })
    positions.clear()

    # 7. 输出结果
    _print_results("全市场", trades, equity_curve, strategy.initial_capital)
    _plot_equity_curve("全市场", equity_curve, strategy.initial_capital)

    return trades, equity_curve


def _run_single(ts_code: str):
    """单股回测（兼容旧版）"""
    bt_start = get_config("backtest.start_date", "20250801")
    bt_end = get_config("backtest.end_date", "20260804")
    train_start = get_config("backtest.train_start_date", "20240101")

    log.info(f"=== 单股回测: {ts_code} ===")
    log.info(f"  训练数据: {train_start} ~ {bt_start}")
    log.info(f"  回测期间: {bt_start} ~ {bt_end}")

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

    for i in range(len(test_df)):
        row = test_df.iloc[i]
        current_price = row["close"]
        current_date = row["trade_date"]
        prob = row["prob"]

        if position is not None:
            should_sell, reason = strategy.should_sell(position, current_price)
            if should_sell:
                pnl = (current_price - position["cost_price"]) / position["cost_price"]
                capital += position["shares"] * current_price
                trades.append({
                    "buy_date": position["buy_date"],
                    "sell_date": current_date,
                    "buy_price": position["cost_price"],
                    "sell_price": current_price,
                    "shares": position["shares"],
                    "pnl": pnl,
                    "reason": reason,
                })
                log.info(f"卖出 {current_date} @ {current_price:.2f} | {reason} | {pnl:.1%}")
                position = None

        if position is None:
            if strategy.should_buy(prob, threshold):
                buy_amount = capital * strategy.position_size
                shares = int(buy_amount / current_price / 100) * 100
                if shares > 0:
                    capital -= shares * current_price
                    position = {
                        "shares": shares,
                        "cost_price": current_price,
                        "buy_date": current_date,
                        "holding_days": 0,
                    }
                    log.info(f"买入 {current_date} @ {current_price:.2f} | {shares}股 | 概率: {prob:.2f}")

        if position is not None:
            position["holding_days"] += 1

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

    _print_results(ts_code, trades, equity_curve, strategy.initial_capital)
    _plot_equity_curve(ts_code, equity_curve, strategy.initial_capital)
    return trades, equity_curve


def _print_results(name, trades, equity_curve, initial_capital):
    """打印回测结果"""
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
    log.info(f"回测结果: {name}")
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
    log.info(f"交易记录已保存: {RESULT_DIR / f'trades_{name}.csv'}")


def _plot_equity_curve(name, equity_curve, initial_capital):
    """绘制收益曲线"""
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
    log.info(f"收益曲线已保存: {RESULT_DIR / f'equity_{name}.png'}")
