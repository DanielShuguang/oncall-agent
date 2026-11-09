# 前端镜像：Node 构建静态资源，Nginx 托管并反代 /api（含 SSE 不缓冲）。
FROM node:22-slim AS build

WORKDIR /app

# 不用 corepack：它在不同 Node 小版本上的启用方式变过，直接装锁定的 pnpm 更可复现
RUN npm install --global pnpm@10.34.3

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
