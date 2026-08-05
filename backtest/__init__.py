"""
回测引擎

流程:
  1. 下载历史数据
  2. 计算因子
  3. 训练模型
  4. 逐日回测: 模型预测 → 买入 → 持仓检查 → 卖出
  5. 输出收益曲线和统计指标

用法:
  python -m backtest run 000001.SZ
  python -m backtest run_all
"""
import sys
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


def run_backtest(ts_code: str, start_date: str = None, end_date: str = None):
    """对单只股票回测"""
    start_date = start_date or get_config("backtest.start_date", "20200101")
    end_date = end_date or get_config("backtest.end_date", "20260804")

    log.info(f"=== 回测开始: {ts_code} [{start_date} ~ {end_date}] ===")

    # 1. 下载数据
    log.info("下载日线数据...")
    df = data.get_daily(ts_code, start_date, end_date)
    log.info(f"获取 {len(df)} 条数据")

    # 2. 计算因子
    log.info("计算因子...")
    df = compute_factors(df)

    # 3. 训练模型（用前 80% 数据训练）
    log.info("训练模型...")
    model = LimitUpModel()
    train_end = int(len(df) * 0.8)
    train_df = df.iloc[:train_end]
    metrics = model.train(train_df)
    log.info(f"训练完成 | 准确率: {metrics['accuracy']:.2%}")

    # 4. 回测（用后 20% 数据）
    log.info("开始逐日回测...")
    test_df = df.iloc[train_end:].copy()
    test_df["prob"] = model.predict(test_df)
    threshold = get_config("model.predict_threshold", 0.5)

    strategy = Strategy()
    capital = strategy.initial_capital
    position = None  # 当前持仓
    trades = []  # 交易记录
    equity_curve = []  # 收益曲线

    for i in range(len(test_df)):
        row = test_df.iloc[i]
        current_price = row["close"]
        current_date = row["trade_date"]
        prob = row["prob"]

        # --- 检查是否卖出 ---
        if position is not None:
            should_sell, reason = strategy.should_sell(position, current_price)
            if should_sell:
                # 卖出
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
                log.info(f"卖出 {current_date} @ {current_price:.2f} | {reason} | 盈亏: {pnl:.1%}")
                position = None

        # --- 检查是否买入 ---
        if position is None:
            if strategy.should_buy(prob, threshold):
                buy_amount = capital * strategy.position_size
                shares = int(buy_amount / current_price / 100) * 100  # A股100股整手
                if shares > 0:
                    capital -= shares * current_price
                    position = {
                        "shares": shares,
                        "cost_price": current_price,
                        "buy_date": current_date,
                        "holding_days": 0,
                    }
                    log.info(f"买入 {current_date} @ {current_price:.2f} | {shares}股 | 概率: {prob:.2f}")

        # 更新持仓天数
        if position is not None:
            position["holding_days"] += 1

        # 记录每日净值
        position_value = position["shares"] * current_price if position else 0
        equity = capital + position_value
        equity_curve.append({"date": current_date, "equity": equity})

    # 如果最后还有持仓，按最后收盘价平仓
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

    # 5. 输出结果
    _print_results(ts_code, trades, equity_curve, strategy.initial_capital)
    _plot_equity_curve(ts_code, equity_curve, strategy.initial_capital)

    return trades, equity_curve


def _print_results(ts_code, trades, equity_curve, initial_capital):
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

    # 最大回撤
    eq = pd.Series([e["equity"] for e in equity_curve])
    peak = eq.cummax()
    drawdown = (eq - peak) / peak
    max_drawdown = drawdown.min()

    log.info("=" * 50)
    log.info(f"回测结果: {ts_code}")
    log.info("=" * 50)
    log.info(f"总交易次数: {len(trades)}")
    log.info(f"胜率: {win_rate:.1%}")
    log.info(f"平均盈利: {avg_win:.1%}" if avg_win else "平均盈利: 无")
    log.info(f"平均亏损: {avg_loss:.1%}" if avg_loss else "平均亏损: 无")
    log.info(f"盈亏比: {profit_factor:.2f}")
    log.info(f"总收益率: {total_return:.1%}")
    log.info(f"最大回撤: {max_drawdown:.1%}")
    log.info(f"最终资金: {final_equity:,.0f}")
    log.info("=" * 50)

    # 保存交易记录
    RESULT_DIR.mkdir(exist_ok=True)
    df_trades.to_csv(RESULT_DIR / f"trades_{ts_code}.csv", index=False, encoding="utf-8-sig")
    log.info(f"交易记录已保存: {RESULT_DIR / f'trades_{ts_code}.csv'}")


def _plot_equity_curve(ts_code, equity_curve, initial_capital):
    """绘制收益曲线"""
    if not equity_curve:
        return

    df = pd.DataFrame(equity_curve)
    plt.figure(figsize=(12, 6))
    plt.plot(df["equity"].values, label="Equity", color="blue")
    plt.axhline(y=initial_capital, color="gray", linestyle="--", label="Initial Capital")
    plt.title(f"Equity Curve - {ts_code}")
    plt.xlabel("Days")
    plt.ylabel("Capital")
    plt.legend()
    plt.tight_layout()
    RESULT_DIR.mkdir(exist_ok=True)
    plt.savefig(RESULT_DIR / f"equity_{ts_code}.png", dpi=150)
    plt.close()
    log.info(f"收益曲线已保存: {RESULT_DIR / f'equity_{ts_code}.png'}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "run":
        code = sys.argv[2]
        run_backtest(code)
    else:
        print("用法: python -m backtest run 000001.SZ")
