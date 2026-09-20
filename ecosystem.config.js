/**
 * PM2 全局进程守护配置文件 (Auto-JobHunter)
 * 
 * 功能：
 * 1. 24小时守护前后端服务，遇异常崩溃 1 秒内自动拉起。
 * 2. 每天凌晨 02:00 定时自动重启后端与前端，彻底清空积攒内存。
 * 3. 内存熔断保护 (后端 800M / 前端 600M)，防止异常死循环拖垮系统。
 */
module.exports = {
  apps: [
    {
      name: 'jobhunter-backend',
      cwd: './backend',
      script: './.venv/bin/uvicorn',
      args: 'app.main:app --host 127.0.0.1 --port 8000',
      interpreter: 'none',
      cron_restart: '0 2 * * *', // 每天凌晨 02:00 自动重启
      max_memory_restart: '800M', // 内存超 800M 熔断重置
      autorestart: true,
      restart_delay: 500, // 崩溃后 500ms 拉起（SIGKILL 即死内核即刻回收 socket，实测无端口冲突；满足崩溃自愈 1 秒内目标）
      min_uptime: '10s', // 连续运行 10 秒以上重置重启计数器
      kill_timeout: 5000, // 优雅退出超时 5 秒
      watch: false,
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: './logs/backend-error.log',
      out_file: './logs/backend-out.log',
      env: {
        PYTHONUNBUFFERED: '1',
      },
    },
    {
      name: 'jobhunter-frontend',
      cwd: './frontend',
      script: 'node_modules/next/dist/bin/next',
      args: 'dev -p 3000',
      interpreter: 'node',
      cron_restart: '5 2 * * *', // 每天凌晨 02:05 自动重启
      max_memory_restart: '600M', // 内存超 600M 熔断重置
      autorestart: true,
      watch: false,
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: './logs/frontend-error.log',
      out_file: './logs/frontend-out.log',
      env: {
        NODE_ENV: 'development',
        PORT: '3000',
      },
    },
  ],
};
