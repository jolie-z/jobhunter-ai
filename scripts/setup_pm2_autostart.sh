#!/bin/bash
# 一键配置 PM2 开机自启（macOS 用户级 LaunchAgent）
#
# 作用：
#   1. 生成本用户的 LaunchAgent（~/Library/LaunchAgents/pm2.<user>.plist），
#      每次登录时自动执行 `pm2 resurrect`，按 ~/.pm2/dump.pm2 快照拉起
#      jobhunter 前后端（含凌晨 2 点 cron 重启、内存熔断等全部配置）。
#   2. 立即加载该 agent 并触发一次 resurrect 做验证。
#
# 注意：
#   - 快照依赖 `pm2 save`；start_pm2.sh 已在每次启动后自动 save。
#   - 若通过 nvm 升级了 Node，pm2 的绝对路径会变化，届时需重新运行本脚本。
#   - LaunchAgent 在"用户登录"时触发（非开机未登录状态）；个人 Mac 正常使用无差别。

set -euo pipefail

LABEL="pm2.$(whoami)"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
UID_NUM="$(id -u)"

PM2_BIN="$(command -v pm2)" || { echo "❌ 未找到 pm2，请先安装"; exit 1; }
NODE_DIR="$(dirname "$(command -v node)")"

# 快照防护：只有 jobhunter 服务在运行时才刷新快照，避免把空列表存进 dump
if pm2 jlist 2>/dev/null | grep -q "jobhunter"; then
  pm2 save
else
  echo "⚠️  当前没有 jobhunter 服务在运行，跳过 pm2 save（请先执行 scripts/start_pm2.sh）"
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.pm2"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PM2_BIN}</string>
        <string>resurrect</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${NODE_DIR}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>ProcessType</key>
    <string>Background</string>
    <key>StandardOutPath</key>
    <string>${HOME}/.pm2/launchd-out.log</string>
    <key>StandardErrorPath</key>
    <string>${HOME}/.pm2/launchd-err.log</string>
</dict>
</plist>
EOF

# 重复执行本脚本时先卸载旧任务，避免残留
launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || launchctl remove "${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${UID_NUM}" "$PLIST"

echo ""
echo "✅ PM2 开机自启已配置完成！"
echo "   - LaunchAgent: ${PLIST}"
echo "   - 触发时机: 每次登录自动执行 pm2 resurrect，按 dump.pm2 恢复前后端"
echo "   - 验证命令: launchctl print gui/${UID_NUM}/${LABEL}"
