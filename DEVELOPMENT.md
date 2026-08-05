# 协作开发任务清单

> 本文档列出所有待开发任务，供两名开发者分工协作。
> 每完成一项请在对应位置打勾 `[x]` 并提交 commit。

---

## 项目概览

| 项目 | 说明 |
|------|------|
| 策略名称 | A股涨停预测捕捉策略 V2.0 |
| 策略类型 | 事件驱动·多头·涨停预测 |
| 部署平台 | VN.PY 3.x / QMT MiniQMT |
| 数据源 | Tushare Pro API |
| 回测范围 | 2020-01-01 至今 |
| Python版本 | 3.8 - 3.10 |

---

## 代码结构总览

```
predict_limit-up/
├── config/              # 配置层
│   ├── config.yaml     # ★ 所有策略参数（权重/阈值/规则）
│   └── settings.py     # 配置加载器
├── data_fetch/         # 数据获取层
│   ├── tushare_client.py   # Tushare API 封装
│   ├── stock_data.py       # 行情数据获取
│   ├── event_data.py       # 事件数据获取
│   └── cache.py            # 数据缓存
├── models/             # 模型层
│   ├── factors/        # 五维因子
│   │   ├── information.py   # 信息面因子
│   │   ├── capital.py       # 资金面因子
│   │   ├── technical.py     # 技术面因子
│   │   ├── chip.py          # 筹码面因子
│   │   └── market.py        # 市场面因子
│   ├── nfrm.py         # NFRM 多因子共振模型
│   ├── lgm.py          # LGM 涨停基因模型
│   └── ahs.py          # AHS 竞价健康度评分
├── strategy/           # 策略层
│   ├── signal_generator.py  # 信号生成引擎
│   ├── entry.py             # 入场管理（五阶段建仓）
│   ├── exit.py              # 出场管理（止盈止损）
│   └── position_manager.py  # 仓位管理（凯利公式）
├── risk/               # 风控层
│   ├── filters.py      # 一票否决过滤器（14项）
│   └── risk_checker.py # 风控检查器
├── scanner/            # 扫描层
│   ├── tail_scan.py        # 尾盘异动扫描
│   ├── overnight_scan.py   # 隔夜信息扫描
│   ├── auction_monitor.py  # 集合竞价监控
│   └── open_confirm.py     # 开盘确认
├── backtest/           # 回测层
│   └── engine.py       # 回测引擎
├── live/               # 实盘层
│   ├── vnpy_strategy.py    # VN.PY 策略模板
│   └── qmt_strategy.py     # QMT 策略模板
├── utils/              # 工具层
│   └── logger.py       # 日志工具
├── tests/              # 测试
├── logs/               # 运行日志
└── scripts/            # 脚本工具
```

---

## 分工建议

建议按 **层** 分工，每人负责完整的垂直切片：

| 模块 | 开发者A | 开发者B | 说明 |
|------|---------|---------|------|
| 数据获取层 `data_fetch/` | ✅ 主力 | 协助 | Tushare封装、数据预处理、缓存 |
| 五维因子 `models/factors/` | ✅ 主力 | | 信息/资金/技术/筹码/市场因子实现 |
| 三大模型 `models/` | ✅ 主力 | | NFRM/LGM/AHS 模型整合 |
| 扫描层 `scanner/` | | ✅ 主力 | 四个扫描模块实现 |
| 策略层 `strategy/` | 协助 | ✅ 主力 | 信号生成/入场/出场/仓位 |
| 风控层 `risk/` | | ✅ 主力 | 14项否决+风控检查 |
| 回测层 `backtest/` | | ✅ 主力 | 回测引擎+绩效分析 |
| 实盘层 `live/` | 共同 | 共同 | VN.PY / QMT 对接 |
| 测试 `tests/` | 共同 | 共同 | 单元测试+集成测试 |

---

## 任务清单

### P0 - 数据层（先做，其他模块依赖）

- [ ] **T01** `data_fetch/tushare_client.py` — 补全所有 Tushare 接口封装，添加频率限制和重试机制
- [ ] **T02** `data_fetch/stock_data.py` — 实现前复权日线、分钟线、涨停历史数据获取
- [ ] **T03** `data_fetch/event_data.py` — 实现公告分类规则引擎（关键词→评级映射）
- [ ] **T04** `data_fetch/cache.py` — 完善缓存读写，添加缓存命中率统计
- [ ] **T05** 搭建 Tushare 数据下载脚本 `scripts/download_data.py`，批量下载 2020 年至今的日线、涨停、龙虎榜数据到本地缓存

### P1 - 因子层

- [ ] **T10** `models/factors/information.py` — 补全公告评级、政策催化、舆情热度、美股映射四项评分
- [ ] **T11** `models/factors/capital.py` — 补全主力净流入、北向资金、大单占比、封单强度四项评分
- [ ] **T12** `models/factors/technical.py` — 补全量价配合、均线系统、MACD、K线形态四项评分
- [ ] **T13** `models/factors/chip.py` — 补全筹码集中度、套牢盘、股东变化三项评分（需 Wind/iFinD 数据源）
- [ ] **T14** `models/factors/market.py` — 补全板块共振、大盘环境、市场情绪三项评分

### P2 - 模型层

- [ ] **T20** `models/nfrm.py` — 验证五维加权逻辑，调试非线性放大效应阈值
- [ ] **T21** `models/lgm.py` — 实现涨停次数、连板率、封板成功率统计计算
- [ ] **T22** `models/ahs.py` — 验证竞价涨幅/量能比/委托比/价格漂移四项评分

### P3 - 策略层

- [ ] **T30** `strategy/signal_generator.py` — 整合 NFRM+LGM+AHS，验证信号分级逻辑
- [ ] **T31** `strategy/entry.py` — 实现五阶段建仓节奏，竞价挂单+开盘加仓+回封加仓
- [ ] **T32** `strategy/exit.py` — 实现事件驱动止盈+技术性止盈+7层止损体系
- [ ] **T33** `strategy/position_manager.py` — 实现凯利公式仓位计算+组合风险预算

### P4 - 风控层

- [ ] **T40** `risk/filters.py` — 逐个实现14项一票否决检查
- [ ] **T41** `risk/risk_checker.py` — 实现仓位上限、板块集中度、大盘熔断、黑名单管理
- [ ] **T42** `risk/risk_checker.py` — 实现黑名单 SQLite 持久化存储

### P5 - 扫描层

- [ ] **T50** `scanner/tail_scan.py` — 实现尾盘异动扫描（量比+涨幅+大单）
- [ ] **T51** `scanner/overnight_scan.py` — 实现隔夜信息扫描（公告+政策+美股+舆情）
- [ ] **T52** `scanner/auction_monitor.py` — 实现集合竞价实时监控+AHS计算
- [ ] **T53** `scanner/open_confirm.py` — 实现6项秒板确认信号+弱势信号检测

### P6 - 回测层

- [ ] **T60** `backtest/engine.py` — 实现完整回测引擎（逐日模拟）
- [ ] **T61** 编写回测绩效分析: 胜率、盈亏比、最大回撤、夏普比率
- [ ] **T62** 编写收益曲线可视化 `backtest/plotting.py`

### P7 - 实盘层

- [ ] **T70** `live/vnpy_strategy.py` — 继承 CtaTemplate，实现 VN.PY 完整策略
- [ ] **T71** `live/qmt_strategy.py` — 继承 Context，实现 QMT 完整策略
- [ ] **T72** 实现定时任务调度（APScheduler 注册 14:30/20:00/09:15/09:30）

### P8 - 测试

- [ ] **T80** 为五维因子编写单元测试
- [ ] **T81** 为三大模型编写单元测试
- [ ] **T82** 为信号生成编写集成测试
- [ ] **T83** 为回测引擎编写端到端测试

### P9 - 工程

- [ ] **T90** 配置 GitHub Actions CI（lint + test）
- [ ] **T91** 编写部署文档
- [ ] **T92** 编写实盘运维手册

---

## 验收标准

| 验收项 | 通过标准 |
|--------|----------|
| 代码编译 | 无语法错误，可正常导入 |
| 回测胜率 | NFRM≥65分标的次日涨停率 > 55% |
| 回测盈亏比 | > 2.0 |
| 实盘模拟 | 连续5个交易日无异常报错 |
| 风控有效性 | 所有一票否决项正确触发 |
| 日志完整性 | 每笔交易记录完整（时间、价格、数量、信号等级） |

---

## Git 协作规范

### 分支策略

```
main        — 稳定版本，只通过 PR 合入
develop     — 开发主分支
feature/T01-tushare-client   — 功能分支（任务编号-简述）
```

### Commit 规范

```
feat: 新功能
fix: 修复bug
refactor: 重构
test: 测试
docs: 文档

示例:
feat(data_fetch): T01 完成 Tushare 客户端封装
fix(models): 修复 NFRM 非线性放大阈值判断
```

### PR 流程

1. 从 `develop` 拉取功能分支
2. 完成开发后提交 PR 到 `develop`
3. 另一人 Code Review 后合入
4. 定期将 `develop` 合入 `main` 发布

---

## 环境配置

```bash
# 1. 克隆仓库
git clone <repo-url>
cd predict_limit-up

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate    # Linux/Mac
venv\Scripts\activate       # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 TUSHARE_TOKEN

# 5. 验证安装
python -c "from config.settings import config; print('OK')"
```
