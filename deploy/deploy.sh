#!/bin/bash
# 小图兔部署：本机打 bundle_xiaotutu.tar.gz 上传 /tmp 后执行
# 用法：bash deploy/deploy.sh
set -e
REL=/opt/xiaotutu
[ -f /tmp/bundle_xiaotutu.tar.gz ] || { echo '缺少 /tmp/bundle_xiaotutu.tar.gz'; exit 1; }
mkdir -p $REL
tar xzf /tmp/bundle_xiaotutu.tar.gz -C $REL
# 保留 .env（含 IMAGE_TAG / DATABASE_URL）
cp /opt/xiaotutu/.env $REL/.env 2>/dev/null || true
cd $REL
docker compose -p xiaotutu build
docker compose -p xiaotutu up -d
# 健康检查：/api/health 返回 status:ok
HEALTH=""
for i in $(seq 1 12); do
  sleep 5
  HEALTH=$(curl -sS -m 10 http://127.0.0.1:7780/api/health || true)
  echo "$HEALTH" | grep -q '"status": *"ok"' && break
done
if echo "$HEALTH" | grep -q '"status": *"ok"'; then
  echo "小图兔部署成功"
else
  echo "健康检查失败（${HEALTH:0:120}），回滚"
  docker compose -p xiaotutu down
  exit 1
fi
