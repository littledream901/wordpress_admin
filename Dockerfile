# ==============================================
# Stage 1: 前端构建
# ==============================================
FROM node:18-alpine AS web-builder

WORKDIR /opt/vue-fastapi-admin/web

# 使用 pnpm 构建（与 lockfile 一致）
RUN corepack enable && corepack prepare pnpm@latest --activate

COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --registry=https://registry.npmmirror.com

COPY web/ ./
RUN pnpm run build

# ==============================================
# Stage 2: 后端 + Nginx 运行环境
# ==============================================
FROM python:3.11-slim-bookworm

WORKDIR /opt/vue-fastapi-admin

# 系统依赖 & 时区
RUN sed -i "s@http://.*.debian.org@http://mirrors.ustc.edu.cn@g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        nginx \
        curl \
        procps \
        default-mysql-client \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 后端源码
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY run.py ./
COPY pyproject.toml ./

# 前端产物
COPY --from=web-builder /opt/vue-fastapi-admin/web/dist /opt/vue-fastapi-admin/web/dist

# Nginx 配置
COPY deploy/web.conf /etc/nginx/sites-available/default
RUN rm -f /etc/nginx/sites-enabled/default \
    && ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/

# 启动脚本
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 数据目录
RUN mkdir -p /opt/vue-fastapi-admin/data /opt/vue-fastapi-admin/logs

ENV LANG=zh_CN.UTF-8 \
    PYTHONUNBUFFERED=1
EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=20s \
    CMD curl -f http://127.0.0.1/api/v1/base/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
