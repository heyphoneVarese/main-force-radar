# 主力风向标 (Main Force Radar) - AI Coding Agent Guidelines

> 个人自用的 A 股基金主力资金追踪工具。本文件是 AI 编程助手的工作规则,必须严格遵守。

---

## 🚨 RED LINES(绝不可违反)

### R1. 金额必须用整数(分)存储
- ❌ 严禁使用 float 或 Decimal 存储任何金额、净值、份额
- ✅ 净值: int(实际值 × 10000)
- ✅ 金额(元): int(实际值 × 100,即"分")
- ✅ 主力资金: int(实际值 × 10000,即"万元")
- ✅ 份额: int(实际值 × 100)

### R2. 历史数据必须快照
- 每日采集的数据必须冻结当时状态入库
- 永不依赖外部 API 的"实时回查"

### R3. 不做投资建议,只做客观信号
- ❌ 永不输出"建议买入 X 基金"
- ❌ 永不输出"看涨/看跌"等预测
- ✅ 只输出客观数据 + 信号标签(利好/利空/预警)

### R3.1. 信号枚举值不得包含操作指令词汇
- ❌ 严禁 buy / sell / long / short / hold 等可被解读为操作指令的词
- ✅ 使用客观情绪词:bullish / bearish / warning(对应 利好/利空/预警)
- 适用范围:DB 字段值、API 响应、推送文案、前端展示

### R4. 单用户系统,无需登录
- 不做用户注册、登录、权限系统
- 全局唯一用户

### R5. 数据源仅限公开免费渠道
- 主数据源:akshare
- 禁止集成需付费的 Wind、同花顺 iFinD

### R6. 防止 AI 过度工程化
- 不做用户系统、不做支付、不做权限
- 不引入 Redis、Kafka、Elasticsearch
- 不做微服务,单体应用
- 如果觉得"为未来扩展性"要加什么,先停下来问用户

---

## 📋 项目定位

**一句话**:每天 3 次告诉用户:主力在买啥、卖啥、主线是啥、持仓怎么办。

**用户场景**:
- 8:30 推送:盘前报告
- 14:00 推送:盘中主力雷达
- 21:00 推送:收盘复盘
- 周日 20:00:周报

---

## 🏗️ 技术栈(锁死)

- 后端: Python 3.11 + FastAPI + SQLAlchemy 2.0
- 数据: akshare
- 数据库: PostgreSQL (prod) / SQLite (dev)
- 定时任务: APScheduler
- AI: Anthropic Claude API
- 前端: Vue 3 + TypeScript + Tailwind + Element Plus
- 推送: Server酱
- 部署: Docker + Docker Compose

---

## 📂 项目结构

main-force-radar/
├── AGENTS.md
├── README.md
├── .env.example
├── docker-compose.yml
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── src/
│       ├── main.py
│       ├── config.py
│       ├── db.py
│       ├── models/
│       ├── schemas/
│       ├── api/
│       ├── services/
│       │   ├── data_fetcher.py
│       │   ├── signal_engine.py
│       │   ├── push_service.py
│       │   └── ai_analyst.py
│       ├── jobs/
│       └── utils/
│           ├── money.py
│           ├── fund_code.py
│           └── date_helper.py
└── frontend/
    ├── package.json
    └── src/
        ├── main.ts
        ├── App.vue
        ├── views/
        │   ├── Radar.vue
        │   ├── Holdings.vue
        │   └── Settings.vue
        └── components/

---

## 🗄️ 核心数据库表

详细 schema 在后续任务中给出,核心表:
- funds (基金信息)
- holdings (我的持仓)
- fund_nav_daily (基金每日净值)
- sector_flow_daily (板块资金流)
- north_flow_intraday (北向资金)
- signals (信号记录)
- push_logs (推送日志)
- user_config (用户配置)

---

## ✅ 开发节奏(必须按此顺序)

### Phase 1: 基础设施 (Week 1)
1. 项目初始化
2. 数据库 schema + 迁移
3. utils/money.py + 单元测试
4. akshare 采集脚本
- 里程碑: 能拉到今日板块资金流并入库

### Phase 2: 核心功能 (Week 2)
5. 持仓管理 API + 前端
6. 基金 → 板块关联
7. 信号引擎 (bullish/bearish/warning) — 代码字段使用 bullish/bearish/warning,确保不在 UI 层渗透 buy/sell 词汇
- 里程碑: 网页能看到"今日雷达"

### Phase 3: 推送系统 (Week 3)
8. Server酱推送
9. 报告模板
10. Claude API 集成
11. 定时任务
- 里程碑: 微信收到每日推送

### Phase 4: 上线 (Week 4)
12. Docker 化
13. 部署到云服务器
14. 周报 + 高级信号
- 里程碑: 正式上线自用

---

## 🚫 反模式(不要做)

1. 不要引入用户认证(单用户)
2. 不要做基金推荐
3. 不要做策略回测
4. 不要做技术指标(MACD/KDJ)
5. 不要做付费功能
6. 不要用 float 存金额
7. 不要在 API 直接调 akshare(必须先入库)
8. 不要让前端直接调 Claude API
9. 不要把 API key 写死

---

## 🆘 遇到问题必须停下来问用户

1. 需求文档没覆盖的功能
2. 涉及"未来扩展性"的设计
3. 引入新的依赖库
4. 修改数据库 schema
5. 修改 AGENTS.md 本身

不要擅自决策,不要"为了通用性而过度设计"。

---

**最后更新: 2026-05-24**
