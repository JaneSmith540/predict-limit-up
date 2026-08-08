from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

REPORT_DIR = Path(__file__).parent.parent / 'reports'
REPORT_DIR.mkdir(exist_ok=True)

def generate_market_report(engine, statistics=None, name='market', parameters=None):
    stats = statistics or {}
    params = parameters or {}
    df = engine.daily_df
    if df is not None and len(df) > 0:
        initial = params.get('initial_capital', 1000000)
        df = df.copy()
        df['balance'] = df['net_pnl'].cumsum() + initial
        plt.figure(figsize=(14, 6))
        plt.plot(df.index, df['balance'].values, label='Equity', color='royalblue', linewidth=1.5)
        plt.axhline(y=initial, color='gray', linestyle='--', label='Initial Capital')
        plt.fill_between(df.index, initial, df['balance'].values,
                         where=df['balance'].values >= initial, alpha=0.15, color='green')
        plt.fill_between(df.index, initial, df['balance'].values,
                         where=df['balance'].values < initial, alpha=0.15, color='red')
        plt.title('Equity Curve - ' + name, fontsize=14)
        plt.xlabel('Date')
        plt.ylabel('Capital')
        plt.legend()
        plt.tight_layout()
        png_path = REPORT_DIR / ('equity_' + name + '.png')
        plt.savefig(png_path, dpi=150)
        plt.close()
    html = '<html><head><meta charset=UTF-8></head><body>'
    html += '<h1>Backtest Report - ' + name + '</h1>'
    html += '<h2>Parameters</h2><table border=1>'
    for k, v in params.items():
        html += '<tr><td>' + str(k) + '</td><td>' + str(v) + '</td></tr>'
    html += '</table>'
    html += '<h2>Statistics</h2><table border=1>'
    for k, v in stats.items():
        if isinstance(v, float):
            v = str(round(v, 4))
        html += '<tr><td>' + str(k) + '</td><td>' + str(v) + '</td></tr>'
    html += '</table>'
    if df is not None and len(df) > 0:
        html += '<h2>Equity Curve</h2><img src=equity_' + name + '.png style=width:100%>'
    html += '</body></html>'
    html_path = REPORT_DIR / ('report_' + name + '.html')
    html_path.write_text(html, encoding='utf-8')
    print('Report: ' + str(html_path))
    return str(html_path)

def generate_single_report(ts_code, trades, equity_curve, initial_capital, parameters=None):
    stats = {}
    if trades:
        df_t = pd.DataFrame(trades)
        stats['total_trades'] = len(trades)
        stats['win_rate'] = str(round((df_t['pnl'] > 0).mean() * 100, 1)) + '%'
        total_ret = (equity_curve[-1]['equity'] - initial_capital) / initial_capital
        stats['total_return'] = str(round(total_ret * 100, 1)) + '%'
    class FakeE:
        daily_df = None
    return generate_market_report(FakeE(), statistics=stats, name=ts_code, parameters=parameters or {})
