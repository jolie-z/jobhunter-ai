// 飞书集成中心 (Feishu Hub) 类型定义
export interface FeishuChat {
  chat_id: string
  name: string
}

export interface DiagCheck {
  key: string
  label: string
  ok: boolean
  detail: string
  fix?: string
}

export interface DiagResult {
  all_ok: boolean
  checked_at: string
  ws_running: boolean
  chats_count: number
  chats: FeishuChat[]
  checks: DiagCheck[]
}

export interface Goals {
  id: number
  start_date: string
  status: string
  daily_deliver_target: number
  daily_crawl_target: number
  weekly_interview_target: number
  total_offer_target: number
  plan_days: number
  report_time_daily: string
  report_time_weekly: string
  report_time_monthly: string
  report_enabled_daily: number | boolean
  report_enabled_weekly: number | boolean
  report_enabled_monthly: number | boolean
  feishu_receive_id: string
  days_elapsed: number
  time_progress_percent: number
  today_crawled: number
  daily_crawl_progress: number
  today_delivered: number
  daily_deliver_progress: number
  total_delivered: number
  total_interview: number
  total_offer: number
  suggested_daily_crawl: number | null
  crawl_conversion_rate: number
  data_maturity_note?: string
}

export interface GoalsForm {
  daily_deliver_target: number
  daily_crawl_target: number
  weekly_interview_target: number
  total_offer_target: number
  plan_days: number
  report_time_daily: string
  report_time_weekly: string
  report_time_monthly: string
  report_enabled_daily: boolean
  report_enabled_weekly: boolean
  report_enabled_monthly: boolean
}
