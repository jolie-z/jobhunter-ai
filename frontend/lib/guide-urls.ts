/**
 * 在线教程与反馈入口（运营小服务器上的静态页，更新教程无需重新发包）。
 *
 * 部署位置：telemetry/public/guide/*.html → 服务器 /guide/*（见 telemetry/server.js）。
 * 已切到 HTTPS 域名（nginx 反代 telemetry），与 desktop/telemetry.js 的 DEFAULT_URL 一致；
 * IP 直连地址保留给已装机的老版本桌面端。
 */
export const GUIDE_BASE_URL = "https://jobhunter.joliezeng.top"

export const GUIDE_URLS = {
  BASE: GUIDE_BASE_URL,
  HOME: `${GUIDE_BASE_URL}/guide`,
  FEISHU: `${GUIDE_BASE_URL}/guide/feishu`,
  LLM: `${GUIDE_BASE_URL}/guide/llm`,
  PIPELINE: `${GUIDE_BASE_URL}/guide/pipeline`,
  DASHBOARD: `${GUIDE_BASE_URL}/guide/dashboard`,
  CUSTOM_PANEL: `${GUIDE_BASE_URL}/guide/custom-panel`,
  FEEDBACK: `${GUIDE_BASE_URL}/guide/feedback`,
} as const

export const GUIDE_HOME_URL = GUIDE_URLS.HOME
export const FEISHU_GUIDE_URL = GUIDE_URLS.FEISHU
export const LLM_GUIDE_URL = GUIDE_URLS.LLM
export const PIPELINE_GUIDE_URL = GUIDE_URLS.PIPELINE
export const DASHBOARD_GUIDE_URL = GUIDE_URLS.DASHBOARD
export const CUSTOM_PANEL_GUIDE_URL = GUIDE_URLS.CUSTOM_PANEL
export const FEEDBACK_URL = GUIDE_URLS.FEEDBACK

/** 外链统一走新窗口（Electron 壳会把外部 URL 交给系统浏览器，见 desktop/main.js setWindowOpenHandler） */
export function openGuide(url: string) {
  window.open(url, "_blank", "noopener,noreferrer")
}
