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

回测结束后会自动在 `reports/` 下生成一份静态报告。报告包含独立 PNG 图表、
汇总 PDF、标准化每日结果、成交记录、FIFO 配对交易、每日持仓、指标和运行元数据。
全市场报告使用沪深300和中证500作为基准；基准数据缓存在
`data_cache/benchmarks/`。生成结果和缓存均不会进入 Git。

报告只对已有回测结果做后处理，不参与模型预测、选股、买卖、仓位或撮合。

PDF 依次覆盖绩效总览、风险诊断、月度收益、每日交易活动、完整交易结果、
持仓与资金使用、贡献与集中度，以及最多 10 只重点股票的交易时间线。
报告口径如下：

- 收益按日复合，年化统一使用 240 个交易日；策略与基准在首个共同有效日归零。
- 报告按配置中的回测起始日截断，预热数据不计入收益、交易或图表。
- 完整交易按股票 FIFO 配对，未平仓标为 `open_at_end`，不计入胜率和交易分布。
- 停牌或缺失收盘价使用前一可得收盘价，使用次数会写入 `metadata.json`。
- 基准网络请求失败时优先使用缓存；缓存也不可用时仍生成报告并明确标注缺失。

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
├── visualization/       # 静态图表、指标和PDF报告
├── utils/               # 工具（配置加载+日志）
└── logs/                # 输出日志和收益曲线
```

