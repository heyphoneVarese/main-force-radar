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

## VPS 部署(Phase 4.12)

阿里云 2核2G Ubuntu 22.04 上海 验证目标,其他 Linux VPS 同理。

### 一次性准备

1. **VPS 装 docker**:
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo systemctl enable --now docker
   sudo usermod -aG docker $USER   # 重新 SSH 登录生效
   ```

2. **clone 仓库 + 准备 .env**:
   ```bash
   git clone https://github.com/heyphoneVarese/main-force-radar.git
   cd main-force-radar
   cp .env.example backend/.env
   vi backend/.env
   ```
   `.env` 必填:
   - `ANTHROPIC_API_KEY=sk-ant-...`
   - `SERVER_CHAN_SCKEY=SCT...`
   - `SCHEDULER_ENABLED=true` ← **VPS 必须改 true**,默认 false 不会触发 cron

3. **起服务**:
   ```bash
   docker compose up -d --build
   ```
   首次构建 ~5-10 分钟(akshare 依赖较多)。后续改代码 `git pull && docker compose up -d --build` 增量很快。

4. **初始化数据库 + 种子**(只第一次):
   ```bash
   docker compose exec backend uv run python -m scripts.init_db
   docker compose exec backend uv run python -m scripts.seed_funds
   docker compose exec backend uv run python -m scripts.import_my_holdings
   ```

5. **验证**:
   ```bash
   curl http://localhost:8000/health
   # 期望: {"status":"ok","service":"main-force-radar","scheduler_enabled":true,"scheduler_running":true}
   curl http://localhost/api/holdings
   # 期望: 52 条 holding JSON 数组
   ```

6. **阿里云安全组**:开 **80**(HTTP)。22(SSH)默认开。8000 不必对公网开 —— nginx 在 80 上反代 `/api` 到 backend 容器内部。

### 日常使用

- 浏览器 `http://VPS_PUBLIC_IP/` 看持仓页(手机也可,移动卡片视图自动切换)
- `docker compose logs -f backend` 看 scheduler 日志(包含 AI 调用 + 推送结果)
- `docker compose logs -f` 看全部
- 改了代码:`git pull && docker compose up -d --build`
- 看 push 历史:
  ```bash
  docker compose exec backend sqlite3 /app/data/main_force_radar.db \
    "SELECT pushed_at, push_type, status FROM push_logs ORDER BY pushed_at DESC LIMIT 20;"
  ```

### 注意事项

- **SQLite 数据**在 `backend/data/main_force_radar.db`(host 卷挂载),`docker compose down` 不删数据,`down -v` 才删
- **`backend/.env` 不要提交到 git**(已 gitignore;包含 API key + SCKEY)
- **SCHEDULER_ENABLED=true** 后,4 个 cron 自动跑(Asia/Shanghai 时区):
  - 12:55 mon-fri 盘前简报
  - 14:30 mon-fri 盘中观察
  - 15:30 mon-fri 收盘复盘
  - 16:00 fri 周报
- **Server酱免费版日限 5 条**,工作日 3 条 + 周五额外 1 条 = ≤ 4,够用
- **akshare 在 VPS 上可访问 eastmoney**(本机海外环境拉不到的 `sector_flow_daily` 应该能跑通了。本地遗留 mock 数据 30 天 sector_flow 会跟真数据混在一起;首次 VPS 跑前可考虑 `DELETE FROM sector_flow_daily;` 清掉再重新 fetch)
