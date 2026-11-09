# 前端镜像：Node 构建静态资源，Nginx 托管并反代 /api（含 SSE 不缓冲）。
FROM node:22-slim AS build

ENV PNPM_HOME=/pnpm \
    PATH="/pnpm:$PATH"

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@10.34.3 --activate

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
