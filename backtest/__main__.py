import sys
from backtest import run_backtest

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'run':
        run_backtest()
    else:
        print('Usage: python -m backtest run')
