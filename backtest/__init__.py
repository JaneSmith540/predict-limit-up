"""
全市场回测引擎（无未来函数）

流程:
  1. 获取回测期间的交易日历（含预热期）
  2. 收集训练用的涨停样本（训练期内有过涨停的股票历史数据）
  3. 训练多元线性回归模型（因子已 shift(1) 滞后，标签为当日涨停）
  4. 逐日回测:
     a. 获取当日全市场行情
     b. 执行昨日挂单（次日开盘价成交）
     c. 用最近N天历史数据计算rolling因子（按股票分组）
     d. 用当日收盘价检查持仓止损/止盈/到期 → 生成次日卖单
     e. 模型预测全市场 → 选top N → 生成次日买单
     f. 记录每日净值
  5. 输出收益曲线和统计指标

交易时序: t日收盘信号 → t+1日开盘成交（杜绝当日信号当日交易）

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
    warmup_days = 20

    log.info("=" * 60)
    log.info("全市场涨停预测回测（无未来函数）")
    log.info(f"  训练数据: {train_start} ~ {bt_start}")
    log.info(f"  回测期间: {bt_start} ~ {bt_end}")
    log.info(f"  每日选股: {daily_pick} | 最大持仓数: {max_positions}")
    log.info(f"  交易时序: t日收盘信号 → t+1日开盘成交")
    log.info("=" * 60)

    # 1. 获取交易日历（含预热期）
    log.info("获取交易日历...")
    pre_days = data.get_trade_cal(train_start, bt_start)
    warmup_trade_days = [d for d in pre_days if d < bt_start][-warmup_days:]
    trade_days = data.get_trade_cal(bt_start, bt_end)
    log.info(f"预热天数: {len(warmup_trade_days)} | 回测交易日数: {len(trade_days)}")

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

    # 5. 预热：下载回测前的历史数据（用于计算rolling因子）
    log.info(f"下载预热数据（{len(warmup_trade_days)}天）...")
    data_history = {}
    for d in warmup_trade_days:
        try:
            data_history[d] = data.get_daily_all(d)
        except Exception as e:
            log.debug(f"跳过预热日 {d}: {e}")

    # 6. 逐日回测
    log.info("开始全市场逐日回测...")
    strategy = Strategy()
    capital = strategy.initial_capital
    positions = {}
    trades = []
    equity_curve = []
    pending_buys = []
    pending_sells = []

    for day_idx, trade_date in enumerate(trade_days):
        # --- A. 获取当日全市场行情 ---
        try:
            today_data = data.get_daily_all(trade_date)
        except Exception as e:
            log.warning(f"获取{trade_date}数据失败: {e}")
            continue
        if today_data is None or len(today_data) == 0:
            continue
        data_history[trade_date] = today_data

        # --- B. 执行昨日挂单：次日开盘价成交 ---
        # 先卖后买，释放资金
        for sell in pending_sells:
            code = sell["ts_code"]
            if code not in positions:
                continue
            pos = positions[code]
            stock_row = today_data[today_data["ts_code"] == code]
            if len(stock_row) == 0:
                continue
            sell_price = stock_row.iloc[0]["open"]
            pnl = (sell_price - pos["cost_price"]) / pos["cost_price"]
            capital += pos["shares"] * sell_price
            trades.append({
                "ts_code": code,
                "buy_date": pos["buy_date"],
                "sell_date": trade_date,
                "buy_price": pos["cost_price"],
                "sell_price": sell_price,
                "shares": pos["shares"],
                "pnl": pnl,
                "reason": sell["reason"],
            })
            log.info(f"[{trade_date}] 卖出 {code} @ {sell_price:.2f} (开盘) | {sell['reason']} | {pnl:.1%}")
            del positions[code]
        pending_sells = []

        slots = max_positions - len(positions)
        if slots > 0:
            for signal in pending_buys[:slots]:
                code = signal["ts_code"]
                if code in positions:
                    continue
                stock_row = today_data[today_data["ts_code"] == code]
                if len(stock_row) == 0:
                    continue
                buy_price = stock_row.iloc[0]["open"]
                buy_amount = capital * strategy.position_size
                shares = int(buy_amount / buy_price / 100) * 100
                if shares < 100:
                    continue
                capital -= shares * buy_price
                positions[code] = {
                    "shares": shares,
                    "cost_price": buy_price,
                    "buy_date": trade_date,
                    "holding_days": 0,
                }
                log.info(f"[{trade_date}] 买入 {code} @ {buy_price:.2f} (开盘) | {shares}股 | 概率: {signal['prob']:.4f}")
        pending_buys = []

        # --- C. 计算因子（用最近N天历史数据，按股票分组rolling） ---
        recent_dates = sorted(data_history.keys())[-warmup_days:]
        combined = pd.concat([data_history[d] for d in recent_dates], ignore_index=True)
        combined = compute_factors(combined)
        market_data = combined.sort_values(["ts_code", "trade_date"]).groupby("ts_code").tail(1).reset_index(drop=True)

        # --- D. 检查持仓：用当日收盘价判断止损/止盈/到期 → 次日开盘卖 ---
        for code, pos in list(positions.items()):
            pos["holding_days"] += 1
            stock_row = market_data[market_data["ts_code"] == code]
            if len(stock_row) == 0:
                continue
            current_price = stock_row.iloc[0]["close"]
            should_sell, reason = strategy.should_sell(pos, current_price)
            if should_sell:
                pending_sells.append({"ts_code": code, "reason": reason})

        # --- E. 模型预测：因子基于t-1及更早数据，预测当日涨停 → 次日开盘买 ---
        valid_data = market_data.dropna(subset=get_factor_columns())
        if len(valid_data) > 0:
            probs = model.predict(valid_data)
            valid_data = valid_data.copy()
            valid_data["prob"] = probs
            top_n = valid_data.nlargest(daily_pick, "prob")
            pending_buys = [{"ts_code": r["ts_code"], "prob": r["prob"]} for _, r in top_n.iterrows()]
        else:
            pending_buys = []

        # --- F. 记录每日净值 ---
        position_value = 0
        for code, pos in positions.items():
            stock_row = market_data[market_data["ts_code"] == code]
            if len(stock_row) > 0:
                position_value += pos["shares"] * stock_row.iloc[0]["close"]
        equity = capital + position_value
        equity_curve.append({"date": trade_date, "equity": equity})

        # 清理过期数据（只保留最近warmup_days天）
        if len(data_history) > warmup_days:
            old_dates = sorted(data_history.keys())[:-warmup_days]
            for d in old_dates:
                del data_history[d]

        if (day_idx + 1) % 20 == 0:
            log.info(f"  回测进度: {day_idx+1}/{len(trade_days)} | 净值: {equity:,.0f} | 持仓: {len(positions)}")

    # 7. 回测结束，平仓所有持仓（按最后一天收盘价）
    last_date = trade_days[-1]
    last_data = data_history.get(last_date, today_data)
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

    # 8. 输出结果
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
    pending_buy = False
    pending_sell = False
    sell_reason = ""

    for i in range(len(test_df)):
        row = test_df.iloc[i]
        current_price = row["close"]
        current_date = row["trade_date"]
        prob = row["prob"]

        # --- 执行昨日挂单：今日开盘成交 ---
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
            log.info(f"卖出 {current_date} @ {sell_price:.2f} (开盘) | {sell_reason} | {pnl:.1%}")
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
                log.info(f"买入 {current_date} @ {buy_price:.2f} (开盘) | {shares}股 | 概率: {prob:.2f}")
            pending_buy = False

        # --- 用当日收盘价检查止损/止盈/到期 → 次日开盘卖 ---
        if position is not None:
            position["holding_days"] += 1
            should_sell, reason = strategy.should_sell(position, current_price)
            if should_sell:
                pending_sell = True
                sell_reason = reason

        # --- 用当日因子（基于t-1数据）预测 → 次日开盘买 ---
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
