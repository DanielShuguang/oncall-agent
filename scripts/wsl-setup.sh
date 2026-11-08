#!/usr/bin/env bash
# 在 WSL(Ubuntu) 内准备 Docker 环境 —— 本机无管理员权限时用这条路。
#
# 用法（Windows PowerShell）：
#   wsl -d Ubuntu -u root -- bash /mnt/e/workspace/github/oncall/scripts/wsl-setup.sh
#
# 说明：
# - 本机 WSL 是用 Ubuntu Base rootfs 导入的（无 systemd、无 CA 证书），脚本会先引导补证书
# - APT 镜像按候选列表自动探测，第一个可用的胜出
# - 只准备环境，不起项目；起项目用：pwsh -File scripts/dev.ps1 docker-up

set -euo pipefail

log() { printf '\n\033[36m==> %s\033[0m\n' "$*"; }

# Windows 侧配了 localhost 代理时，WSL NAT 模式下连不通，必须清掉
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy || true

export DEBIAN_FRONTEND=noninteractive

SRC=/etc/apt/sources.list.d/ubuntu.sources
[ -f "$SRC" ] || SRC=/etc/apt/sources.list
ORIG="${SRC}.oncall-orig"
[ -f "$ORIG" ] || cp "$SRC" "$ORIG"

# 首次引导：镜像没有 CA 证书，先关校验；装完 ca-certificates 后恢复严格校验
APT_BOOT=(-o Acquire::https::Verify-Peer=false -o Acquire::https::Verify-Host=false)

CANDIDATES=(
  "https://mirrors.aliyun.com/ubuntu/"
  "https://mirrors.ustc.edu.cn/ubuntu/"
  "https://mirror.nju.edu.cn/ubuntu/"
  "https://repo.huaweicloud.com/ubuntu/"
  "https://mirrors.tuna.tsinghua.edu.cn/ubuntu/"
)

log "探测可用 APT 镜像"
PICKED=""
for m in "${CANDIDATES[@]}"; do
  cp "$ORIG" "$SRC"
  sed -i -E "s#^URIs: .*#URIs: ${m}#" "$SRC"
  printf '  trying %s ... ' "$m"
  if apt-get "${APT_BOOT[@]}" update -y >/tmp/apt-probe.log 2>&1; then
    echo "OK"
    PICKED="$m"
    break
  fi
  echo "FAIL ($(grep -m1 -oE '403|404|Could not|Failed' /tmp/apt-probe.log || echo 'unknown'))"
done
[ -n "$PICKED" ] || { echo "所有镜像均不可用，请检查网络或代理配置"; exit 1; }

log "安装 CA 证书（$PICKED）"
apt-get "${APT_BOOT[@]}" install -y --no-install-recommends ca-certificates

log "恢复严格校验并更新索引"
apt-get update -y

log "安装 docker.io / docker-compose-v2"
apt-get install -y --no-install-recommends \
  docker.io docker-compose-v2 ca-certificates curl iproute2 iptables

log "配置镜像加速器（Docker Hub 在境内直连会超时）"
mkdir -p /etc/docker
cat >/etc/docker/daemon.json <<'JSON'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.1ms.run",
    "https://docker.xuanyuan.me"
  ],
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "3" }
}
JSON

log "启动 docker 守护进程"
if [ "$(ps -p 1 -o comm= 2>/dev/null || true)" = "systemd" ]; then
  systemctl enable --now docker
else
  # rootfs 导入的 WSL 没有 systemd，用 SysV 脚本 + dockerd 兜底
  service docker start 2>/dev/null || true
  if ! docker info >/dev/null 2>&1; then
    mkdir -p /var/log
    nohup dockerd >/var/log/dockerd.log 2>&1 &
    for _ in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 1; done
  fi
fi

log "验证"
docker version --format 'docker {{.Server.Version}}'
docker compose version
docker info --format 'os={{.OSType}} arch={{.Architecture}} driver={{.Driver}}'

log "完成。回到 Windows 执行：pwsh -File scripts/dev.ps1 docker-up"
