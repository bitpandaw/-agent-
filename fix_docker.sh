#!/bin/bash
# 修复 Docker 拉取镜像超时 - 先尝试直连 Docker Hub
set -e

echo "1. 移除镜像配置，直连 Docker Hub..."
sudo rm -f /etc/docker/daemon.json

echo "2. 重启 Docker..."
sudo service docker restart

echo "3. 等待 Docker 就绪..."
sleep 3

echo "4. 测试 hello-world..."
docker run hello-world

echo ""
echo "成功！"
