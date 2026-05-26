# Frontend Dockerfile - Phase 4.12
#
# 两阶段:
#   1) node:20-alpine - 装 deps + vite build
#   2) nginx:alpine   - 装上一阶段产物 dist/ + 反代 /api → backend:8000
#
# 最终镜像 ~50MB(node 阶段产物丢弃,只留 nginx + 静态文件)。
#
# 构建:在仓库根目录执行
#   docker compose build frontend

# ============ Build stage ============
FROM node:20-alpine AS build

WORKDIR /app

# 装 deps 单独一层(缓存友好)
COPY package*.json ./
RUN npm ci

# 业务代码
COPY . .

# 现在 client.ts 写死 '/api' 相对路径,VPS 走 nginx 反代到 backend
# 留这个 ARG 是为了未来想换成绝对 URL 时不用改 Dockerfile
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# ============ Serve stage ============
FROM nginx:alpine

# 替掉 nginx 默认 conf — 我们要 SPA fallback + /api 反代
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 复制 vite 产物
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# nginx:alpine 默认 CMD ["nginx", "-g", "daemon off;"],不用覆盖
