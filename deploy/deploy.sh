#!/bin/bash
# 小图兔部署：本机打 bundle_xiaotutu.tar.gz 上传 /tmp 后执行
# 用法：bash deploy/deploy.sh
set -e
REL=/opt/xiaotutu
[ -f /tmp/bundle_xiaotutu.tar.gz ] || { echo '缺少 /tmp/bundle_xiaotutu.tar.gz'; exit 1; }
mkdir -p $REL
# 保留旧 .env（含 IMAGE_TAG / DATABASE_URL）：先备份，解压后再恢复（首次部署无旧 .env 则用 bundle 自带）
cp $REL/.env /tmp/xiaotutu_env.bak 2>/dev/null || true
tar xzf /tmp/bundle_xiaotutu.tar.gz -C $REL
if [ -f /tmp/xiaotutu_env.bak ]; then cp /tmp/xiaotutu_env.bak $REL/.env; echo '已恢复旧 .env'; fi
cd $REL
docker compose -p xiaotutu build
docker compose -p xiaotutu up -d
# 健康检查：经 nginx（对外 80）反代到 app，/api/health 返回 status:ok
# 注：app 只 expose 7780（内部网络），宿主机 7780 不通，须走 80；冷启动导入 onnxruntime/opencv 等较慢，放宽到 120s
HEALTH=""
for i in $(seq 1 24); do
  sleep 5
  HEALTH=$(curl -sS -m 10 http://127.0.0.1:80/api/health || true)
  echo "$HEALTH" | grep -q '"status": *"ok"' && break
done
if echo "$HEALTH" | grep -q '"status": *"ok"'; then
  echo "小图兔部署成功"
else
  echo "健康检查失败（${HEALTH:0:120}），回滚"
  docker compose -p xiaotutu down
  exit 1
fi
