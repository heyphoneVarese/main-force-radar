# 主力风向标 (Main Force Radar)

个人自用的 A 股基金主力资金追踪工具。详见 [AGENTS.md](./AGENTS.md)。

## 本地启动

### 准备

```bash
cp .env.example .env
# 按需填 .env(Phase 1 不需要填,默认 SQLite 即可跑起来)
```

### Backend

需要 Python 3.11 + [uv](https://github.com/astral-sh/uv)。

```bash
cd backend
uv sync                                       # 安装依赖到 .venv
uv run uvicorn src.main:app --reload --port 8000
```

打开 http://localhost:8000/health 应返回 `{"status":"ok","service":"main-force-radar"}`。
API 文档:http://localhost:8000/docs

### Frontend

需要 Node 18+。

```bash
cd frontend
npm install
npm run dev
```

打开 http://localhost:5173。

## 项目阶段

- [x] Phase 1 / 第 1 步:项目初始化
- [ ] Phase 1 / 第 2 步:数据库 schema + 迁移
- [ ] Phase 1 / 第 3 步:utils/money.py + 单元测试
- [ ] Phase 1 / 第 4 步:akshare 采集脚本

后续阶段见 [AGENTS.md](./AGENTS.md)。
