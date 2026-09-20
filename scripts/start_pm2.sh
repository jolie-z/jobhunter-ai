#!/bin/bash
# 一键启动 / 重启 PM2 守护进程

# 获取项目根目录
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 1

# 确保日志目录存在
mkdir -p "$ROOT_DIR/backend/logs" "$ROOT_DIR/frontend/logs"

echo "=========================================="
echo "🚀 正在启动 Auto-JobHunter (PM2 守护模式)..."
echo "=========================================="

# 先安全清理旧的散落进程与无用浏览器
pkill -f "next-server" 2>/dev/null || true
pkill -f "postcss.js" 2>/dev/null || true
pkill -f "uvicorn" 2>/dev/null || true
pkill -f "data/profiles" 2>/dev/null || true

# 启动 PM2 配置
pm2 startOrReload ecosystem.config.js

# 立即固化快照，保证 dump.pm2 与最新配置同步（供开机自启的 pm2 resurrect 使用）
pm2 save

echo ""
echo "✅ PM2 守护服务已就绪！"
echo "📊 当前运行状态如下："
pm2 list

echo ""
echo "💡 提示："
echo " - 查看实时日志: pm2 logs"
echo " - 停止所有服务: ./scripts/stop_pm2.sh 或 pm2 stop all"
echo " - 重启所有服务: pm2 restart all"
