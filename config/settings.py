"""
全局配置加载器
- 从 .env 读取敏感信息（Tushare token 等）
- 从 config.yaml 读取策略参数
- 提供统一的 Config 单例供全局访问
"""

import os
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv


# 项目根目录 (predict_limit-up/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 加载 .env 文件
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    """
    全局配置单例

    用法:
        from config.settings import config
        token = config.tushare_token
        nfrm_weights = config.get("nfrm.weights")
    """

    _instance = None
    _data: Dict[str, Any] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self):
        """加载 config.yaml"""
        config_path = PROJECT_ROOT / "config" / "config.yaml"
        if not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        with open(config_path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f)

    @property
    def tushare_token(self) -> str:
        """从环境变量读取 Tushare token（不写入代码/配置文件）"""
        token = os.getenv("TUSHARE_TOKEN", "")
        if not token:
            raise ValueError(
                "TUSHARE_TOKEN 未设置，请在项目根目录创建 .env 文件并填入 token"
                "（参考 .env.example）"
            )
        return token

    @property
    def tushare_api_url(self) -> str:
        return self.get("data_source.tushare.api_url", "https://api.tushare.pro")

    def get(self, dot_key: str, default: Any = None) -> Any:
        """
        通过点号路径获取嵌套配置值
        例: config.get("nfrm.weights.information") -> 0.25
        """
        keys = dot_key.split(".")
        value = self._data
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def get_section(self, section: str) -> Dict[str, Any]:
        """获取整个配置段"""
        return self.get(section, {})

    def reload(self):
        """重新加载配置（热更新）"""
        self._load()


# 全局配置实例
config = Config()
