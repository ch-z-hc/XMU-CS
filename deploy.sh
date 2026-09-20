#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

./.venv/bin/python fetch_schedule.py --no-open "$@"
# 2026-09-17：WordPress 目录已删，这个部署目标早就没了（跑了就是往不存在的目录里装）。
# 课表现在挂在私密域名下，产物落 /srv/private/site/schedule，由 nginx 的 auth_request 挡着。
WWW_ROOT="/srv/private/site/schedule"
sudo install -m 644 -D schedule.html "$WWW_ROOT/index.html"
sudo install -m 644 -D manifest.json "$WWW_ROOT/manifest.json"
sudo install -d "$WWW_ROOT/assets"
sudo install -m 644 -D assets/icon-192.png "$WWW_ROOT/assets/icon-192.png"
sudo install -m 644 -D assets/icon-512.png "$WWW_ROOT/assets/icon-512.png"
sudo install -m 644 -D assets/apple-touch-icon.png "$WWW_ROOT/assets/apple-touch-icon.png"
sudo install -m 644 -D assets/favicon.png "$WWW_ROOT/assets/favicon.png"
echo "已部署到 https://private.chzhc.cn/schedule/（需入口口令）"
