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
