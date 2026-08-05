"""
工具模块：配置加载 + 日志
"""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from loguru import logger

# 项目根目录
PROJECT_ROOT = Path(__file__).parent

# 加载 .env
load_dotenv(PROJECT_ROOT / ".env")

# 加载 config.yaml
with open(PROJECT_ROOT / "config.yaml", "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

# Tushare token（从环境变量读取）
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")


def get_config(key: str, default=None):
    """从 config.yaml 读取配置，用点号分隔。例: get_config('trading.position_size')"""
    value = CONFIG
    for k in key.split("."):
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default
    return value


# 日志配置
logger.remove()
logger.add(
    lambda msg: print(msg, end=""),
    level=get_config("logging.level", "INFO"),
    format="{time:HH:mm:ss} | {level:<7} | {message}",
)
logger.add(
    str(PROJECT_ROOT / "logs" / "run.log"),
    level="DEBUG",
    rotation="1 day",
    retention="30 days",
    encoding="utf-8",
)

log = logger
