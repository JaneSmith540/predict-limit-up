"""回测入口

用法:
  python -m backtest run              # 全市场回测（最近1年）
  python -m backtest run 000001.SZ     # 单股回测
"""
import sys
from backtest import run_backtest

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "run":
        ts_code = sys.argv[2] if len(sys.argv) >= 3 else None
        run_backtest(ts_code)
    else:
        print("用法:")
        print("  python -m backtest run              # 全市场回测")
        print("  python -m backtest run 000001.SZ     # 单股回测")
