# Docker 编排归档（已弃用）

本目录存放项目早期的 Docker Compose 编排模板（继承自 FastAPI full-stack 模板），
**已于 2026-08 决定弃用**，原因：

1. **反爬指纹是硬约束**：四大平台爬虫全部依赖真实 Edge 浏览器（有头模式 +
   `--disable-blink-features=AutomationControlled`）+ 物理隔离的持久化 Profile
   （`backend/data/profiles/`）。容器内 headless/Chromium 指纹已被实践证伪
   （见 `backend/51job_scraper/开发笔记.md` 方案 1/2 废弃记录）。
2. **人工介入无法闭环**：Boss 扫码登录（等待 300s）、安全滑块、智联验证码
   均依赖真人在宿主机浏览器上操作。
3. **模板残留不完整**：无 frontend/Dockerfile、未 COPY 爬虫目录、未安装浏览器、
   `--workers 4` 与 APScheduler/LangGraph 单例冲突。

正确的部署方式是**宿主机常驻**（见 README「生产部署」一节）。
若未来需要混合部署（前端+API 容器化、爬虫留宿主机），需先将 CDP 地址
`127.0.0.1` 参数化并重构进程管理，再参考本归档重写编排。
