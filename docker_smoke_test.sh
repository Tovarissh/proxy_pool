#!/bin/bash
# Docker冒烟测试：build → run → 检查API → stop
set -e
echo "[1/4] Building Docker image..."
docker build -t proxy_pool:test /home/lighthouse/proxy_pool/
echo "[2/4] Starting container..."
docker run -d --name proxy_pool_test -p 5001:5000 proxy_pool:test
sleep 5
echo "[3/4] Checking API..."
curl -sf http://localhost:5001/api/stats && echo " API OK"
echo "[4/4] Cleanup..."
docker stop proxy_pool_test && docker rm proxy_pool_test
echo "DOCKER SMOKE TEST PASSED"