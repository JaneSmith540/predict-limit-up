"""
日志工具
基于 loguru 封装，统一全项目日志格式

TODO: 协作者可扩展以下功能
- 交易日志单独输出到 logs/trades/
- 飞书/钉钉告警推送
- 日志分级染色
"""

from loguru import logger as _logger
import sys
from pathlib import Path

from config.settings import config, PROJECT_ROOT


def _setup_logger():
    """初始化日志配置"""
    level = config.get("logging.level", "INFO")
    log_format = config.get(
        "logging.format",
        "{time:YYYY-MM-DD HH:mm:ss} | {level: | <8} | {name}:{function}:{line} - {message}",
    )
    log_path = config.get("logging.path", "logs")
    full_log_path = PROJECT_ROOT / log_path
    full_log_path.mkdir(parents=True, exist_ok=True)

    _logger.remove()
    # 控制台输出
    _logger.add(sys.stderr, level=level, format=log_format)
    # 文件输出（每日轮转）
    _logger.add(
        str(full_log_path / "limitup_{time:YYYY-MM-DD}.log"),
        level=level,
        format=log_format,
        rotation=config.get("logging.rotation", "00:00"),
        retention=config.get("logging.retention", "30 days"),
        encoding="utf-8",
    )


_setup_logger()


def get_logger(name: str = __name__):
    """获取 logger 实例"""
    return _logger.bind(name=name)
