#!/usr/bin/env bash
# WSL 内 docker 守护进程管理（本机无 systemd，dockerd 不会自启）
#
# 用法：
#   wsl -d Ubuntu -u root -- bash /mnt/e/workspace/github/oncall/scripts/wsl-docker.sh ensure
#   wsl -d Ubuntu -u root -- bash /mnt/e/workspace/github/oncall/scripts/wsl-docker.sh restart

set -euo pipefail

ensure() {
  if docker info >/dev/null 2>&1; then
    echo "dockerd 已在运行"
    return 0
  fi
  mkdir -p /var/log
  nohup dockerd >/var/log/dockerd.log 2>&1 &
  for _ in $(seq 1 40); do
    if docker info >/dev/null 2>&1; then
      echo "dockerd 已启动"
      return 0
    fi
    sleep 1
  done
  echo "dockerd 启动失败，见 /var/log/dockerd.log" >&2
  tail -20 /var/log/dockerd.log >&2 || true
  return 1
}

case "${1:-ensure}" in
  ensure)
    ensure
    ;;
  restart)
    pkill -f 'docker compose' 2>/dev/null || true
    sleep 1
    pkill dockerd 2>/dev/null || true
    sleep 3
    ensure
    ;;
  *)
    echo "用法: $0 {ensure|restart}" >&2
    exit 2
    ;;
esac
