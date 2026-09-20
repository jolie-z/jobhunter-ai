// ===== 全链路指挥中心全局常量定义 =====

/**
 * 防抖延迟时间（毫秒）
 */
export const DEBOUNCE_DELAY = 300

/**
 * Toast 提示显示时间（毫秒）
 */
export const TOAST_DURATION = 3000

/**
 * 失败岗位重试最大次数限制
 */
export const MAX_RETRY_ATTEMPTS = 3

/**
 * abortMsg 弹窗自动消失时间（毫秒）
 */
export const ABORT_MSG_TIMEOUT = 5000

/**
 * API 请求超时时间（毫秒）
 */
export const API_TIMEOUT = 30000

/**
 * Token 统计刷新间隔（毫秒）
 */
export const TOKEN_STATS_REFRESH_INTERVAL = 60000 // 1 分钟

/**
 * 岗位列表最大渲染数量（虚拟滚动阈值）
 */
export const MAX_JOBS_RENDER_THRESHOLD = 50

/**
 * 平台主题颜色映射
 */
export const PLATFORM_THEME_MAP = {
  boss: { bg: "bg-blue-500/10", text: "text-blue-600 dark:text-blue-400", border: "border-blue-500/20", name: "BOSS" },
  liepin: { bg: "bg-purple-500/10", text: "text-purple-600 dark:text-purple-400", border: "border-purple-500/20", name: "猎聘" },
  zhilian: { bg: "bg-indigo-500/10", text: "text-indigo-600 dark:text-indigo-400", border: "border-indigo-500/20", name: "智联" },
  "51job": { bg: "bg-orange-500/10", text: "text-orange-600 dark:text-orange-400", border: "border-orange-500/20", name: "前程无忧" },
} as const

/**
 * 步骤状态枚举
 */
export enum StageStatus {
  IDLE = "idle",
  RUNNING = "running",
  DONE = "done",
  ERROR = "error",
}

/**
 * Pipeline 任务状态枚举
 */
export enum PipelineTaskStatus {
  IDLE = "idle",
  RUNNING = "running",
  DONE = "done",
  ERROR = "error",
  ABORTING = "aborting",
}

/**
 * UI 组件尺寸常量
 */
export const UI_SIZES = {
  CARD_HEIGHT: 180,
  BUTTON_H: 7, // 高度单位 rem
  PADDING_X: 2.5, // padding-x 单位 rem
} as const
