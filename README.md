# 涨停预测策略 V1

用多元线性回归预测 A 股涨停。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 Tushare token
cp .env.example .env
# 编辑 .env，填入你的 Tushare token

# 3. 运行回测
python -m backtest run 000001.SZ
```

## 项目结构

```
predict_limit-up/
├── config.yaml          # 所有参数配置
├── .env.example         # 环境变量模板（复制为.env填token）
├── data_fetch/          # 数据获取（Tushare封装）
├── factors/             # 因子计算（★ 搭档负责这里加因子）
├── model/               # 多元线性回归模型
├── strategy/            # 买卖策略（止损/止盈/仓位）
├── backtest/            # 回测引擎
├── utils/               # 工具（配置加载+日志）
└── logs/                # 输出日志和收益曲线
```

## 搭档要做什么

在 `factors/__init__.py` 里加因子。当前只有 MA5 和 MA10，你可以加 RSI、MACD、成交量等。

步骤：
1. 在 `config.yaml` 的 `factors` 列表加上因子名
2. 在 `factors/__init__.py` 的 `compute_factors()` 里加计算逻辑
3. 在 `factors/__init__.py` 的 `get_factor_columns()` 里加上因子列名

模型和回测会自动读取新因子，不需要改其他代码。
