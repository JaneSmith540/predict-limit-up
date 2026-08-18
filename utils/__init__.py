import os, logging
from pathlib import Path
import yaml

_env_file = Path(__file__).parent.parent / '.env'
if _env_file.exists():
    for line in open(_env_file, encoding='utf-8'):
        line = line.strip()
        if line and '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

TUSHARE_TOKEN = os.environ.get('TUSHARE_TOKEN', '')

log = logging.getLogger('predict_limit_up')
log.setLevel(logging.INFO)
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', '%H:%M:%S'))
    log.addHandler(h)

_cfg = None

def _load():
    global _cfg
    if _cfg is None:
        with open(Path(__file__).parent.parent / 'config.yaml', encoding='utf-8') as f:
            _cfg = yaml.safe_load(f)
    return _cfg

def get_config(key, default=None):
    val = _load()
    for p in key.split('.'):
        if isinstance(val, dict) and p in val:
            val = val[p]
        else:
            return default
    return val


def is_one_word_limit_up(open_p, high_p, low_p, close_p, pre_close, tol=0.02):
    """判断某根日 K 是否为「一字涨停」板。

    一字涨停指股票以涨停价开盘后全天封死、再无成交
    （open == high == low == close，即日内无任何价格波动区间）。
    这类票现实里散户根本买不进去，回测若默认可买会高估收益，
    因此应在买入前将其过滤掉。

    - pre_close: 前一交易日收盘价，用于推算涨停价（任意板块：
      主板 +10% / 创业板·科创板 +20% / ST +5%）
    - 仅在收盘价确实封死在某一档涨停价、且全天价格被钉死在同一
      价位（一字特征）时才判为 True；盘中曾打开或低开高走涨停
      的票视为可买，不被过滤。

    tol: 价格比较容差（元），兼容浮点与最小变动单位四舍五入。
    """
    if pre_close is None or pre_close <= 0:
        return False
    # 各板块涨停价（保留两位小数，与 A 股最小变动单位一致）
    limit_candidates = [round(pre_close * m, 2) for m in (1.05, 1.10, 1.20)]
    at_limit = any(abs(close_p - c) <= tol for c in limit_candidates)
    if not at_limit:
        return False
    # 一字特征：开/高/低/收同一价（允许浮点误差）
    pinned = (abs(open_p - high_p) <= tol
              and abs(high_p - low_p) <= tol
              and abs(low_p - close_p) <= tol)
    return bool(pinned)
