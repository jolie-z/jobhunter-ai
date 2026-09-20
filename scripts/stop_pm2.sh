#!/bin/bash
# 一键停止 PM2 守护进程并释放资源

echo "=========================================="
echo "🛑 正在停止 Auto-JobHunter 所有服务..."
echo "=========================================="

pm2 stop all 2>/dev/null || true
pm2 delete all 2>/dev/null || true

# 清空快照：防止重启电脑时 LaunchAgent 的 pm2 resurrect 把已停止的服务再拉起来
pm2 save 2>/dev/null || true

# 清理可能残留的自动化浏览器与构建进程
pkill -f "next-server" 2>/dev/null || true
pkill -f "postcss.js" 2>/dev/null || true
pkill -f "uvicorn" 2>/dev/null || true
pkill -f "data/profiles" 2>/dev/null || true

echo "✅ 所有前后端服务与浏览器已安全停止并释放内存！"
