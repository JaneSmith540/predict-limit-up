# 涨停预测策略 V1

基于梯度提升集成模型（CatBoost + LightGBM + XGBoost）预测 A 股涨停，通过 vn.py 回测引擎进行全市场回测验证。采用滚动重训机制，每4个月更新模型以适应市场变化。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 Tushare token
cp .env.example .env
# 编辑 .env，填入你的 Tushare token: TUSHARE_TOKEN=your_token_here

# 3. 运行全市场回测
python -m backtest run
```

回测结束后会自动在 `reports/` 下生成静态可视化报告（HTML + PNG 图表 + CSV 数据）。

## 模型架构

### 买入模型：梯度提升集成 + 滚动重训

- **CatBoost + LightGBM + XGBoost** 线性加权概率平均（默认权重 1:1:1）
- 预测：open(t+1) -> open(t+max_holding+1) 收益 >= label_threshold 的概率
- **滚动重训**：每4个月用最新数据重新训练模型，避免因子分布漂移导致信号消失
- 选股策略：始终选择 Top N 股票，设最低概率下限 0.30 保证信号连续性

### 卖出模型（可选，默认禁用）

- 同样使用梯度提升集成
- 持仓期间每日评估，预测次日上涨概率极低时提前卖出
- 通过 `config.yaml` 中 `model.exit_threshold > 0` 启用

## 因子体系（7个无量纲因子）

| 因子 | 说明 |
|------|------|
| `momentum_5` | 5日动量收益率 |
| `momentum_10` | 10日动量收益率 |
| `ma5_bias` | 收盘价相对MA5偏离度 |
| `ma10_bias` | 收盘价相对MA10偏离度 |
| `volatility_5` | 5日变异系数（波动率/均值） |
| `break_high_10` | 相对10日新高突破比率 |
| `rsi_14` | 14日RSI |

所有因子基于 t-1 收盘价计算，不含当日信息，无未来数据泄漏。因子均为无量纲指标，支持跨股票比较。

## 交易规则

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `position_size` | 0.33 | 单仓位占总资金比例 |
| `max_holding_days` | 3 | 最大持仓天数 |
| `stop_loss` | -4% | 止损线 |
| `take_profit` | 10% | 止盈线 |
| `max_positions` | 3 | 最大同时持仓数 |
| `daily_pick` | 3 | 每日选股数量 |
| `predict_threshold` | 0.40 | 买入概率阈值 |
| `label_threshold` | 2.0% | 正样本收益门槛 |

交易时序：t日收盘信号 -> t+1日开盘成交

## V1 最终版回测结果

回测区间：2025-08-01 ~ 2026-08-04

| 指标 | 数值 |
|------|------|
| 年化收益率 | 47.39% |
| 总收益率 | 50.94% |
| 最大回撤 | -23.44% |
| 交易次数 | 438 |
| Sharpe | 1.59 |
| 收益回撤比 | 1.15 |
| 胜率 | 47.1% |
| 盈亏比 | 1.26 |
| 平仓笔数 | 206 |

详细报告见 `reports/` 目录，包含：
- 权益曲线（v1_equity_curve.png）
- 回撤曲线（v1_drawdown.png）
- 月度收益（v1_monthly_returns.png）
- 交易盈亏分布（v1_trade_pnl.png）
- 综合仪表板（v1_dashboard.png）
- 统计指标表（v1_stats_table.png）
- HTML综合报告（v1_final_report.html）

## 项目结构

```
predict-limit-up/
├── config.yaml              # 所有参数配置（模型/交易/回测）
├── .env.example             # 环境变量模板（复制为.env填token）
├── requirements.txt         # Python依赖
├── _bootstrap.py            # 项目初始化
├── data_fetch/              # 数据获取（Tushare API + 本地缓存）
├── factors/                 # 因子计算（训练端 + 策略端）
│   ├── __init__.py          # compute_factors() 训练端批量计算
│   └── factor.py            # calculate_factors() 策略端实时计算
├── model/                   # 梯度提升集成模型
│   └── __init__.py          # LimitUpModel + ExitModel
├── strategies/              # 策略模块
│   ├── __init__.py          # LimitUpStrategy + Strategy
│   └── limit_up_strategy.py  # vn.py 策略实现（滚动重训）
├── backtest/                # 回测引擎
│   ├── __init__.py           # 全市场回测入口（滚动重训）
│   ├── __main__.py           # CLI入口
│   └── engine.py            # vn.py Tushare回测引擎
├── visualization/           # 静态图表和HTML报告生成
├── utils/                   # 工具（配置加载 + 日志）
├── reports/                 # 回测结果报告（HTML/PNG）
└── logs/                    # 运行日志和交易记录
```

## 配置说明

所有参数集中在 `config.yaml`，无需修改代码即可调整：

- **model**: 模型类型、权重、超参数、阈值
- **trading**: 仓位、止损止盈、持仓天数
- **backtest**: 回测区间、训练区间、选股数量
- **factors**: 启用的因子列表

## 滚动重训机制

V1版本引入滚动重训，解决静态模型在后期信号消失的问题：

1. 将回测期分为3段（每4个月）
2. 每段使用不同时间窗口的训练数据重新训练模型
3. 策略根据当前日期自动选择对应模型
4. 配合最低概率下限（0.30），确保信号持续生成

## 数据说明

- 数据源：Tushare Pro API
- 训练数据：训练期内所有涨停股票（约2000+只）
- 回测数据：全市场A股日线数据（约5500+只）
- 本地缓存：首次下载后缓存到 `data_cache/`，后续运行直接读取
