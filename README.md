# A股涨停预测捕捉策略 V2.0

> 事件驱动·多头·涨停预测·量化实现
>
> 基于《A股预测涨停捕捉策略V2.0》，将策略逻辑转化为可运行的量化代码。

## 策略核心

**五维共振预测涨停**：信息面定方向，资金面定强度，技术面定时机，筹码面定空间，市场面定氛围。

### 时序流程

```
14:30-15:00  尾盘扫描  →  初选池(50-100只) + NFRM初筛
20:00-09:15  隔夜扫描  →  信息面得分更新
09:15-09:25  竞价监控  →  信号池(5-10只) + AHS评分
09:25        开盘价确定 →  竞价挂单(5%-8%仓位)
09:30-09:35  开盘确认  →  加仓(5%-7%)或放弃
09:35-15:00  持仓监控  →  炸板止损/封板持有
次日09:15    次日出场  →  竞价止盈/止损
```

### 三大核心模型

| 模型 | 全称 | 作用 |
|------|------|------|
| NFRM | 多因子共振涨停预测模型 | 五维加权评分，预测涨停概率 |
| LGM | 涨停基因模型 | 评估个股历史涨停基因 |
| AHS | 竞价健康度评分 | 集合竞价阶段实时评分确认 |

## 项目结构

```
predict_limit-up/
├── config/         配置层 — config.yaml(参数) + settings.py(加载器)
├── data_fetch/     数据层 — Tushare封装 + 事件数据 + 缓存
├── models/         模型层 — NFRM/LGM/AHS + 五维因子
├── strategy/       策略层 — 信号生成/入场/出场/仓位
├── risk/           风控层 — 14项否决 + 风控检查
├── scanner/        扫描层 — 尾盘/隔夜/竞价/开盘
├── backtest/       回测层 — 回测引擎
├── live/           实盘层 — VN.PY/QMT策略模板
├── utils/          工具层 — 日志
├── tests/          测试
├── config.yaml     策略参数配置
├── requirements.txt Python依赖
└── DEVELOPMENT.md  协作开发任务清单
```

## 快速开始

```bash
# 1. 克隆仓库
git clone <repo-url>
cd predict_limit-up

# 2. 虚拟环境 + 依赖
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# 3. 配置 Tushare Token
cp .env.example .env
# 编辑 .env: TUSHARE_TOKEN=你的token

# 4. 验证
python -c "from config.settings import config; print('OK')"
```

## 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| 数据源 | Tushare Pro | 日线/涨停/龙虎榜/公告/资金流 |
| 回测框架 | VN.PY 3.x | 兼容实盘部署 |
| 机器学习 | scikit-learn | RandomForest（用户偏好） |
| 配置管理 | PyYAML + python-dotenv | 参数与敏感信息分离 |
| 日志 | loguru | 结构化日志 |
| Python | 3.8 - 3.10 | 与 VN.PY 兼容 |

## 部署平台

- **VN.PY 3.x** — 继承 `CtaTemplate`，实盘自动下单
- **QMT MiniQMT** — 继承 `Context`，极速交易

## 协作

详见 [DEVELOPMENT.md](DEVELOPMENT.md) — 包含完整任务清单、分工建议、Git 规范。

## 风险声明

本策略仅供量化研究学习，不构成投资建议。实盘交易有风险，需充分了解策略逻辑和风险后谨慎决策。
