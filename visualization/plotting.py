"""Static chart rendering for the backtest report."""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
from matplotlib import __version__ as MATPLOTLIB_VERSION
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.font_manager import FontProperties, findfont
from matplotlib.ticker import FuncFormatter, PercentFormatter
import numpy as np
import pandas as pd

from .analysis import (
    _is_close_trade,
    _is_open_trade,
    monthly_returns,
    normalize_benchmark_returns,
    rolling_metrics,
)


RED = "#C23B3B"
GREEN = "#18845B"
BLUE = "#2457A6"
ORANGE = "#D97706"
PURPLE = "#7552A3"
GRID = "#D9DEE8"
TEXT = "#253044"
MUTED = "#687386"


def configure_style() -> None:
    """Configure a Chinese-capable, report-friendly Matplotlib theme."""
    candidates = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    for candidate in candidates:
        try:
            findfont(candidate, fallback_to_default=False)
            selected = candidate
            break
        except Exception:
            selected = "DejaVu Sans"
    plt.rcParams.update(
        {
            "font.family": selected,
            "axes.unicode_minus": False,
            "axes.titleweight": "normal",
            "axes.titlesize": 15,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "axes.edgecolor": "#AAB3C2",
            "axes.labelcolor": TEXT,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "text.color": TEXT,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.7,
            "grid.alpha": 0.8,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def money(value, _position=None):
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 10_000:
        return f"{value / 10_000:.1f}万"
    return f"{value:,.0f}"


def percent_axis(ax):
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=1))


def style_axis(ax, title: str):
    ax.set_title(title, loc="left", color=TEXT, pad=12)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.7)
    ax.grid(axis="x", visible=False)
    ax.tick_params(length=0)


def save_figure(fig, output_dir: Path, name: str, pdf: PdfPages) -> Path:
    path = output_dir / f"{name}.png"
    # Keep every exported page at the documented 12 x 7 inch canvas.
    if name != "01_overview":
        fig.tight_layout(rect=[0.02, 0.04, 0.99, 0.98])
    fig.savefig(path, dpi=180)
    pdf.savefig(fig)
    plt.close(fig)
    return path


def _normalized_series(series: pd.Series) -> pd.Series:
    valid = series.dropna()
    if valid.empty:
        return series * np.nan
    return series / valid.iloc[0] - 1.0


def _comparison_curves(daily: pd.DataFrame, benchmarks: pd.DataFrame) -> pd.DataFrame:
    """Normalize strategy and available benchmarks on their first common date."""
    benchmark_returns = normalize_benchmark_returns(benchmarks, daily.index)
    curves = pd.DataFrame({"策略": daily["balance"]}, index=daily.index)
    for label in benchmark_returns.columns:
        curves[label] = benchmark_returns[label]
    common = curves.dropna(how="any")
    start = common.index[0] if not common.empty else daily.index[0]
    curves["策略"] = daily["balance"] / daily.loc[start, "balance"] - 1.0
    curves.loc[curves.index < start, "策略"] = np.nan
    return curves


def plot_overview(daily, benchmarks, metrics, output_dir, pdf):
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), height_ratios=[2.2, 1], sharex=True)
    curves = _comparison_curves(daily, benchmarks)
    axes[0].plot(curves.index, curves["策略"], color=BLUE, linewidth=2.2, label="策略")
    colors = {"沪深300": ORANGE, "中证500": PURPLE}
    for label in curves.columns:
        if label != "策略":
            axes[0].plot(curves.index, curves[label], color=colors.get(label, MUTED), linewidth=1.5, label=label)
    axes[0].axhline(0, color="#9AA3B1", linestyle="--", linewidth=0.9)
    percent_axis(axes[0])
    axes[0].set_ylabel("累计收益")
    axes[0].legend(frameon=False, ncol=3, loc="upper left")
    style_axis(axes[0], "策略绩效与市场基准")

    axes[1].fill_between(daily.index.to_pydatetime(), daily["drawdown"].values, 0, color=GREEN, alpha=0.25)
    axes[1].plot(daily.index, daily["drawdown"], color=GREEN, linewidth=1.2)
    axes[1].axhline(0, color="#9AA3B1", linewidth=0.8)
    percent_axis(axes[1])
    axes[1].set_ylabel("回撤")
    axes[1].set_xlabel("交易日期")
    axes[1].xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    style_axis(axes[1], "水下回撤")
    dd_start = pd.to_datetime(metrics.get("max_drawdown_start"))
    dd_end = pd.to_datetime(metrics.get("max_drawdown_end"))
    axes[1].axvspan(dd_start, dd_end, color=GREEN, alpha=0.12, label="最大回撤区间")
    axes[1].annotate(
        f"最大回撤 {metrics.get('max_drawdown', 0):.1%}",
        xy=(dd_end, float(daily.loc[dd_end, "drawdown"]) if dd_end in daily.index else float(daily["drawdown"].min())),
        xytext=(8, 10),
        textcoords="offset points",
        fontsize=9,
        color=GREEN,
    )
    values = [
        ("总收益", metrics.get("total_return"), ".1%"),
        ("年化收益", metrics.get("annual_return"), ".1%"),
        ("最大回撤", metrics.get("max_drawdown"), ".1%"),
        ("Sharpe", metrics.get("sharpe_ratio"), ".2f"),
        ("完成交易", metrics.get("closed_round_trips"), ".0f"),
        ("胜率", metrics.get("win_rate"), ".1%"),
    ]
    for index, (label, value, fmt) in enumerate(values):
        x = 0.08 + index * 0.15
        display = "N/A" if value is None or not np.isfinite(value) else format(value, fmt)
        fig.text(x, 0.965, label, color=MUTED, fontsize=9, ha="left")
        fig.text(x, 0.935, display, color=TEXT, fontsize=14, ha="left")
    fig.subplots_adjust(top=0.88, hspace=0.28)
    return fig


def plot_risk(daily, annual_days, output_dir, pdf):
    rolling = rolling_metrics(daily, annual_days)
    fig, axes = plt.subplots(3, 1, figsize=(12, 7), sharex=True)
    axes[0].plot(rolling.index, rolling["volatility_20d"], color=ORANGE, linewidth=1.6)
    axes[0].yaxis.set_major_formatter(PercentFormatter(1.0, decimals=1))
    axes[0].set_ylabel("年化波动率")
    style_axis(axes[0], "滚动风险指标")
    axes[1].plot(rolling.index, rolling["sharpe_60d"], color=PURPLE, linewidth=1.6)
    axes[1].axhline(0, color="#9AA3B1", linewidth=0.8)
    axes[1].set_ylabel("Sharpe")
    style_axis(axes[1], "60日滚动 Sharpe")
    axes[2].plot(rolling.index, rolling["return_60d"], color=BLUE, linewidth=1.5)
    axes[2].axhline(0, color="#9AA3B1", linewidth=0.8)
    axes[2].yaxis.set_major_formatter(PercentFormatter(1.0, decimals=1))
    axes[2].set_ylabel("滚动收益")
    axes[2].set_xlabel("交易日期")
    axes[2].xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    style_axis(axes[2], "60日滚动收益")
    valid = rolling["return_60d"].dropna()
    if not valid.empty:
        for label, timestamp, value, color in [
            ("峰", valid.idxmax(), valid.max(), RED),
            ("谷", valid.idxmin(), valid.min(), GREEN),
        ]:
            axes[2].scatter([timestamp], [value], color=color, s=28, zorder=3)
            axes[2].annotate(
                f"{label} {value:.1%}",
                xy=(timestamp, value),
                xytext=(6, 8 if label == "谷" else -16),
                textcoords="offset points",
                fontsize=9,
                color=color,
            )
    return fig


def plot_monthly(daily, output_dir, pdf):
    table = monthly_returns(daily)
    fig, ax = plt.subplots(figsize=(12, 7))
    columns = list(range(1, 13)) + ["annual"]
    values = table.reindex(columns=columns).to_numpy(dtype=float)
    masked = np.ma.masked_invalid(values)
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("cn_returns", [GREEN, "#F7F7F7", RED])
    finite = np.abs(values[np.isfinite(values)])
    bound = max(float(np.max(finite)) if finite.size else 0.1, 0.05)
    im = ax.imshow(masked, cmap=cmap, vmin=-bound, vmax=bound, aspect="auto")
    ax.set_xticks(range(13), [f"{m}月" for m in range(1, 13)] + ["全年"])
    ax.set_yticks(range(len(table.index)), [str(year) for year in table.index])
    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            value = values[i, j]
            if np.isfinite(value):
                ax.text(j, i, f"{value:.1%}", ha="center", va="center", fontsize=8, color=TEXT)
    ax.set_xlabel("月份")
    ax.set_ylabel("年份")
    style_axis(ax, "月度收益率热力图")
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02, format=PercentFormatter(1.0, decimals=1))
    return fig


def plot_activity(daily, output_dir, pdf):
    fig, axes = plt.subplots(3, 1, figsize=(12, 7), sharex=True)
    pnl = daily["net_pnl"]
    colors = np.where(pnl >= 0, RED, GREEN)
    axes[0].bar(daily.index, pnl, color=colors, width=1.0, alpha=0.82)
    axes[0].yaxis.set_major_formatter(FuncFormatter(money))
    axes[0].set_ylabel("净盈亏")
    style_axis(axes[0], "每日交易活动")
    axes[1].plot(daily.index, daily["turnover"], color=BLUE, linewidth=1.2)
    axes[1].yaxis.set_major_formatter(FuncFormatter(money))
    axes[1].set_ylabel("成交额")
    axes[2].plot(daily.index, daily["commission"], color=ORANGE, linewidth=1.1, label="手续费")
    axes[2].plot(daily.index, daily["slippage"], color=PURPLE, linewidth=1.1, label="滑点")
    trade_axis = axes[2].twinx()
    trade_axis.plot(daily.index, daily["trade_count"], color=BLUE, linewidth=0.9, alpha=0.6, label="成交笔数")
    trade_axis.set_ylabel("成交笔数", color=MUTED)
    trade_axis.grid(False)
    axes[2].set_ylabel("成本")
    axes[2].set_xlabel("交易日期")
    lines = axes[2].get_lines() + trade_axis.get_lines()
    axes[2].legend(lines, [line.get_label() for line in lines], frameon=False, ncol=3, loc="upper left")
    axes[2].xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    style_axis(axes[2], "交易成本")
    return fig


def plot_trade_distribution(round_trips, output_dir, pdf):
    closed = round_trips[round_trips["status"] == "closed"].copy()
    fig, axes = plt.subplots(2, 2, figsize=(12, 7))
    if closed.empty:
        for ax in axes.flat:
            ax.text(0.5, 0.5, "无已完成交易", ha="center", va="center")
    else:
        values = closed["gross_return"].dropna().sort_values()
        axes[0, 0].hist(values, bins=min(20, max(5, len(closed) // 3)), color=BLUE, alpha=0.8)
        axes[0, 0].axvline(0, color="#697386", linewidth=0.8)
        axes[0, 0].xaxis.set_major_formatter(PercentFormatter(1.0, decimals=1))
        axes[0, 0].set_xlabel("单笔收益率")
        axes[0, 0].set_ylabel("交易笔数")
        axes[0, 1].plot(values, np.arange(1, len(values) + 1) / len(values), color=PURPLE, linewidth=1.8)
        axes[0, 1].xaxis.set_major_formatter(PercentFormatter(1.0, decimals=1))
        axes[0, 1].yaxis.set_major_formatter(PercentFormatter(1.0, decimals=1))
        axes[0, 1].set_xlabel("单笔收益率")
        axes[0, 1].set_ylabel("累计占比")
        axes[1, 0].scatter(closed["holding_trading_days"], closed["gross_return"], color=ORANGE, alpha=0.8, edgecolors="none")
        axes[1, 0].axhline(0, color="#697386", linewidth=0.8)
        axes[1, 0].yaxis.set_major_formatter(PercentFormatter(1.0, decimals=1))
        axes[1, 0].set_xlabel("持仓交易日")
        axes[1, 0].set_ylabel("单笔收益率")
        profit = closed.loc[closed["gross_return"] > 0, "gross_return"].dropna()
        loss = closed.loc[closed["gross_return"] <= 0, "gross_return"].dropna()
        data = [values for values in [profit, loss] if len(values)]
        labels = [label for label, values in [("盈利", profit), ("亏损", loss)] if len(values)]
        if data:
            if tuple(int(part) for part in MATPLOTLIB_VERSION.split(".")[:2]) >= (3, 9):
                axes[1, 1].boxplot(data, tick_labels=labels, patch_artist=True)
            else:
                axes[1, 1].boxplot(data, labels=labels, patch_artist=True)
            axes[1, 1].yaxis.set_major_formatter(PercentFormatter(1.0, decimals=1))
            axes[1, 1].set_ylabel("单笔收益率")
    titles = ["单笔交易收益分布", "收益率累计分布", "持仓期限与收益", "盈利与亏损分布"]
    for ax, title in zip(axes.flat, titles):
        style_axis(ax, title)
    return fig


def plot_exit_reasons(round_trips, output_dir, pdf):
    closed = round_trips[round_trips["status"] == "closed"].copy()
    if closed.empty or closed["reason"].isna().all():
        return None
    grouped = closed.assign(reason=closed["reason"].fillna("未标注")).groupby("reason")["gross_return"].mean().sort_values()
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.barh(grouped.index.astype(str), grouped.values, color=np.where(grouped.values >= 0, RED, GREEN))
    ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=1))
    ax.set_xlabel("平均交易收益率")
    style_axis(ax, "按退出原因的平均收益")
    return fig


def plot_positions(positions, output_dir, pdf):
    fig, axes = plt.subplots(4, 1, figsize=(12, 7), sharex=True)
    if positions.empty:
        for ax in axes:
            ax.text(0.5, 0.5, "没有可重建的持仓数据", ha="center", va="center")
    else:
        axes[0].plot(positions.index, positions["position_count"], color=BLUE, linewidth=1.5)
        axes[0].set_ylabel("持仓股票数")
        axes[1].plot(positions.index, positions["gross_exposure"], color=ORANGE, linewidth=1.3, label="总敞口")
        axes[1].plot(positions.index, positions["net_exposure"], color=PURPLE, linewidth=1.3, label="净敞口")
        axes[1].yaxis.set_major_formatter(PercentFormatter(1.0, decimals=1))
        axes[1].set_ylabel("资金敞口")
        axes[1].legend(frameon=False, ncol=2, loc="upper left")
        axes[2].plot(positions.index, positions["turnover_rate"], color=BLUE, linewidth=1.2)
        axes[2].yaxis.set_major_formatter(PercentFormatter(1.0, decimals=1))
        axes[2].set_ylabel("换手率")
        axes[3].plot(positions.index, positions["cash_proxy"], color=GREEN, linewidth=1.3)
        axes[3].yaxis.set_major_formatter(FuncFormatter(money))
        axes[3].set_ylabel("现金代理值")
    axes[3].set_xlabel("交易日期")
    axes[3].xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    axes[3].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    style_axis(axes[0], "每日持仓数量")
    style_axis(axes[1], "持仓与资金敞口")
    style_axis(axes[2], "每日换手率")
    style_axis(axes[3], "现金代理值")
    missing = int(positions.get("missing_price_count", pd.Series(dtype=float)).sum()) if not positions.empty else 0
    if missing:
        forward_filled = int(
            positions.get("forward_filled_price_count", pd.Series(dtype=float)).sum()
        )
        fill_fallback = int(
            positions.get("fill_price_fallback_count", pd.Series(dtype=float)).sum()
        )
        note = f"提示：{missing:,} 个持仓价格缺失；{forward_filled:,} 个以前一收盘价前向填充"
        if fill_fallback:
            note += f"，{fill_fallback:,} 个因无历史收盘价而使用成交价"
        fig.text(0.01, 0.01, note + "。", color=MUTED, fontsize=9)
    return fig


def plot_contribution(round_trips, output_dir, pdf):
    closed = round_trips[round_trips["status"] == "closed"].copy()
    fig, axes = plt.subplots(2, 2, figsize=(12, 7))
    if closed.empty:
        for ax in axes.flat:
            ax.text(0.5, 0.5, "无已完成交易", ha="center", va="center")
    else:
        contribution = closed.groupby("vt_symbol")["gross_pnl"].sum().sort_values()
        selected = pd.concat([contribution.head(10), contribution.tail(10)]).drop_duplicates()
        axes[0, 0].barh(selected.index.astype(str), selected.values, color=np.where(selected.values >= 0, RED, GREEN))
        axes[0, 0].xaxis.set_major_formatter(FuncFormatter(money))
        axes[0, 0].set_xlabel("累计毛盈亏")
        monthly = closed.assign(month=closed["exit_datetime"].dt.to_period("M"))
        month_counts = monthly.groupby("month").size()
        axes[0, 1].bar(month_counts.index.astype(str), month_counts.values, color=BLUE, alpha=0.82)
        axes[0, 1].set_ylabel("完成交易笔数")
        axes[0, 1].tick_params(axis="x", rotation=45)
        active = monthly.groupby("month")["vt_symbol"].nunique()
        axes[1, 0].bar(active.index.astype(str), active.values, color=ORANGE, alpha=0.82)
        axes[1, 0].set_ylabel("活跃股票数")
        axes[1, 0].tick_params(axis="x", rotation=45)
        concentration_values = {}
        for month, group in monthly.groupby("month"):
            total = group["gross_pnl"].abs().sum()
            contribution_values = group.groupby("vt_symbol")["gross_pnl"].sum().abs()
            concentration_values[month] = (contribution_values / total).pow(2).sum() if total else np.nan
        concentration = pd.Series(concentration_values).sort_index()
        axes[1, 1].plot(concentration.index.astype(str), concentration.values, color=PURPLE, marker="o", linewidth=1.4)
        axes[1, 1].set_ylabel("集中度 HHI")
        axes[1, 1].tick_params(axis="x", rotation=45)
    titles = ["股票毛盈亏贡献", "月度完成交易数", "月度活跃股票数", "交易贡献集中度"]
    for ax, title in zip(axes.flat, titles):
        style_axis(ax, title)
    return fig


def plot_timeline(symbol, price_df, trades, output_dir, pdf):
    if price_df.empty:
        return None
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.plot(price_df["date"], price_df["close"], color=BLUE, linewidth=1.5, label="收盘价")
    symbol_trades = trades[trades["vt_symbol"] == symbol]
    opens = symbol_trades[symbol_trades.apply(_is_open_trade, axis=1)]
    closes = symbol_trades[symbol_trades.apply(_is_close_trade, axis=1)]
    if not opens.empty:
        ax.scatter(opens["datetime"], opens["price"], color=RED, marker="^", s=40, label="买入")
    if not closes.empty:
        ax.scatter(closes["datetime"], closes["price"], color=GREEN, marker="v", s=40, label="卖出")
    ax.set_xlabel("交易日期")
    ax.set_ylabel("价格")
    ax.legend(frameon=False, ncol=3, loc="upper left")
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    style_axis(ax, f"重点股票交易时间线：{symbol}")
    return fig


def render_report_figures(
    daily,
    benchmarks,
    round_trips,
    positions,
    metrics,
    annual_days,
    output_dir: Path,
    metadata: dict,
    price_loader=None,
) -> list[Path]:
    """Render all report figures and one vector PDF."""
    configure_style()
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    pdf_path = output_dir.parent / "backtest_report.pdf"
    with PdfPages(pdf_path) as pdf:
        builders = [
            ("01_overview", lambda: plot_overview(daily, benchmarks, metrics, output_dir, pdf)),
            ("02_risk", lambda: plot_risk(daily, annual_days, output_dir, pdf)),
            ("03_monthly_returns", lambda: plot_monthly(daily, output_dir, pdf)),
            ("04_activity", lambda: plot_activity(daily, output_dir, pdf)),
            ("05_trade_distribution", lambda: plot_trade_distribution(round_trips, output_dir, pdf)),
            ("06_positions", lambda: plot_positions(positions, output_dir, pdf)),
            ("07_contribution", lambda: plot_contribution(round_trips, output_dir, pdf)),
        ]
        for name, builder in builders:
            paths.append(save_figure(builder(), output_dir, name, pdf))

        reason_figure = plot_exit_reasons(round_trips, output_dir, pdf)
        if reason_figure is not None:
            paths.append(save_figure(reason_figure, output_dir, "05b_exit_reasons", pdf))

        closed = round_trips[round_trips["status"] == "closed"]
        if not closed.empty and price_loader is not None:
            contribution = closed.groupby("vt_symbol")["gross_pnl"].sum().abs().sort_values(ascending=False)
            for rank, symbol in enumerate(contribution.head(10).index, start=1):
                price_df = price_loader(symbol)
                figure = plot_timeline(symbol, price_df, metadata["trades"], output_dir, pdf)
                if figure is not None:
                    paths.append(save_figure(figure, output_dir, f"08_timeline_{rank:02d}_{symbol}", pdf))
    return paths
