# 猎聘新机登录指南

> 适用场景：在一台**新电脑**上克隆本仓库后，猎聘平台报「❌ 缺少猎聘 Cookie，请先在本地终端运行
> `liepin_cookie_harvester.py` 扫码登录！」或无法登录。老机器日常使用无需重做（登录态已在本机）。

## 为什么新机器都要做一遍

猎聘登录态 Cookie 属于敏感凭证，**按安全设计不入 git**（`.gitignore` 的 `backend/**/*cookies*.json`
规则排除）。所以每台新克隆的机器上这个文件必然不存在，需要现场扫码生成一次。生成后，
岗位抓取、自动投递、在线简历回写三个环节共用这份登录态，不需要重复登录。

## 前置条件

| 条件 | 说明 |
| --- | --- |
| 宿主机浏览器 | 必须装有 **Microsoft Edge 或 Google Chrome** 至少一个。爬虫内核 DrissionPage **不自带浏览器**，直接使用宿主机的 Edge（macOS 默认优先）或 Chrome；两者都没有时，扫码成功了爬虫也照样起不来 |
| Python 环境 | 已安装 [uv](https://docs.astral.sh/uv/)（README「本地启动」同款方式）；没有 uv 也可用 `python3 -m venv` + `pip install -r requirements.txt` 替代 |

## 四步操作（macOS）

```bash
# 0) 进入后端目录，安装依赖（首次运行会自动创建 .venv），然后激活虚拟环境
cd backend
uv sync
source .venv/bin/activate
which python   # 应指向 .../backend/.venv/bin/python；不是的话说明没激活，后续包装进系统环境

# 1) 安装扫码采集器用的 Playwright Chromium 内核
#    （采集器走 Playwright 自带 Chromium，与宿主机 Edge/Chrome 是两条线，都要有）
playwright install chromium

# 2) 确认宿主机浏览器存在（Edge 优先，Chrome 亦可兜底）
ls "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" 2>/dev/null
# 什么都不输出 = 两个都没装，先安装一个再继续；只输出一行 = 只有那一个装了（有一个即可）

# 3) 运行扫码采集器：弹出可见浏览器 → 手机扫码登录猎聘 → 回到终端按回车
python liepin_scraper/liepin_cookie_harvester.py
# 成功标志：生成 backend/liepin_scraper/liepin_cookies.json（脚本会打印保存路径）
```

Windows（在 PowerShell 中执行，步骤编号与 macOS 一一对应）：

```powershell
# 0) 进入后端目录，安装依赖（首次运行会自动创建 .venv），然后激活虚拟环境
cd backend
uv sync
.\.venv\Scripts\Activate.ps1    # 若报「禁止运行脚本」，先执行 Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 1) 安装扫码采集器用的 Playwright Chromium 内核
python -m playwright install chromium

# 2) Windows 无需手动检测：Edge/Chrome 装在默认位置即可，DrissionPage 会自动查找
#    （两者都没装仍会失败，先安装一个）

# 3) 运行扫码采集器：弹出可见浏览器 → 手机扫码登录猎聘 → 回到终端按回车
python liepin_scraper\liepin_cookie_harvester.py
```

## 验证

登录态自检（不依赖任何密钥配置，首次会自动把 cookie 注入 Edge/Chrome profile。
仍在 `backend` 目录、虚拟环境已激活的终端里执行；Windows 在 PowerShell 里执行同一条命令即可）：

```bash
python -c "import sys; sys.path.insert(0, 'liepin_scraper'); from liepin_session import ensure_login; print('登录态:', ensure_login(wait_s=0))"
# 输出「登录态: True」即就绪
```

再端到端验一遍：重新发起一次猎聘抓取任务（指挥中心 / 飞书 ChatOps / 控制台均可），日志出现登录态
校验通过并开始 `[抓取成功]` 入库，即整条链路（登录 → 抓取 → 自动投递 → 简历回写）打通。

## 报错对照表（跳了哪步，报什么错）

| 报错指纹 | 缺了哪一步 |
| --- | --- |
| `ModuleNotFoundError: No module named 'playwright_stealth'` | 步骤 0：没在虚拟环境里装依赖（`which python` 不指向 `.venv`） |
| Playwright 报 Chromium 可执行文件缺失 | 步骤 1：漏了 `playwright install chromium` |
| 爬虫侧 DrissionPage 报找不到浏览器 / 拉起浏览器失败 | 步骤 2：宿主机没装 Edge/Chrome |
| 「❌ 缺少猎聘 Cookie，请先在本地终端运行 liepin_cookie_harvester.py」 | 步骤 3：没跑扫码采集器（抓取入口对 cookie 文件有存在性硬校验） |

## 备选与注意事项

- **从旧机器拷贝 cookie**：把旧机 `backend/liepin_scraper/liepin_cookies.json` 拷到新机同一路径也能用；
  但 Cookie 有有效期，且可能受 IP / 设备风控影响，跨机拷贝随时可能失效，推荐现场重采。
- **Cookie 过期后**：用一段时间又报未登录时，重跑步骤 3 覆盖生成新文件即可。

> ⚠️ **安全红线**：cookie 文件已被 `.gitignore` 排除，切勿手动 `git add -f` 提交或外发给他人。
