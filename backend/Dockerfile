# Backend Dockerfile - Phase 4.12
#
# 单阶段,python:3.11-slim 基础 + uv 装依赖。
# 镜像约 ~500MB(akshare/pandas/numpy 占大头,正常)。
#
# 构建:在仓库根目录执行
#   docker compose build backend
#
# 运行:
#   docker compose up -d backend
#
# 首次跑要初始化 DB(否则 holdings/funds 表不存在):
#   docker compose exec backend uv run python -m scripts.init_db
#   docker compose exec backend uv run python -m scripts.seed_funds
#   docker compose exec backend uv run python -m scripts.import_my_holdings

FROM python:3.11-slim

# uv 装得最稳的方式 — pip 比 COPY --from 兼容性好
# 牺牲 10-20s 构建时间,换零踩坑风险
RUN pip install --no-cache-dir uv==0.5.11

# UV_FROZEN=1 关键:禁止 runtime 偷偷改 lockfile / 重新下依赖。
# 否则容器启动时 uv run 会"补齐"dev 组(black/pytest/ruff),
# 国内 VPS 网络 30s 超时 → uvicorn 起不来 → docker logs 空白。
# (Dockerfile 续行 \ 之间不能塞 # 注释,Docker 会当 ENV 值,所以放这上面)
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_FROZEN=1

WORKDIR /app

# 单独 COPY lockfile + sync,让 docker layer 缓存生效
# (代码改不影响这一层)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 业务代码
COPY src ./src
COPY scripts ./scripts

# SQLite 数据目录(docker-compose 会挂 host 卷过来,持久化)
RUN mkdir -p /app/data

EXPOSE 8000

# 不带 --reload,prod 用单进程 uvicorn(2C2G VPS 单实例够用)
# host 0.0.0.0 必填,否则容器内只听 127.0.0.1 外部访问不到
#
# 关键:--no-dev 必须显式带。
# uv run 默认会"补齐"dev 组依赖(black/pytest/ruff),即便 build 时
# uv sync --no-dev 没装它们,runtime 也会重新去拉,撞国内 PyPI 慢导致
# 启动超时。--no-dev 让 uv run 完全跳过 dev 组,只用 build 时装好的
# prod 依赖。R6 生产不塞开发工具。
CMD ["uv", "run", "--no-dev", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
