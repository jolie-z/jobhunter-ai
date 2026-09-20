/**
 * 数据分析中心统一数据模型与类型定义
 */

export interface OverviewStats {
  total_crawled: number
  today_crawled: number
  yesterday_crawled: number
  total_delivered: number
  total_interview: number
  total_offer: number
  a_grade_count: number
  a_grade_rate: number
  conversion_rate: number
  interview_rate: number
  today_tokens: number
  month_tokens: number
  month_cost_cny: number
  feishu_total: number
  total_pending: number
}

export interface FunnelStage {
  stage: string
  count: number
  percent: number
}

export interface PlatformStat {
  platform: string
  crawl_count: number
  push_count: number
  deliver_count: number
  interview_count: number
  offer_count: number
  deliver_rate: number
}

export interface TrendPoint {
  label: string
  crawled: number
  delivered: number
  interviewed: number
}

export interface GoalData {
  days_elapsed: number
  plan_days: number
  status: string
  daily_crawl_target: number
  daily_deliver_target: number
  today_crawled: number
  today_delivered: number
  time_progress_percent: number
  daily_crawl_progress: number
  daily_deliver_progress: number
  report_time_daily: string
  report_time_weekly: string
  report_time_monthly: string
  report_enabled_daily: number
  report_enabled_weekly: number
  report_enabled_monthly: number
  feishu_receive_id: string
}

// ── Token 审计模型 ──
export interface TokenSummary {
  today_tokens: number
  month_tokens: number
  total_tokens: number
  today_cost_cny: number
  month_cost_cny: number
  total_cost_cny: number
  today_cached_tokens: number
  month_cached_tokens: number
  total_cached_tokens: number
  today_cache_hit_rate: number
  month_cache_hit_rate: number
  total_cache_hit_rate: number
}

export interface ByAction {
  action_name: string
  call_count: number
  total_tokens: number
  cost_cny: number
}

export interface ByModel {
  model_name: string
  call_count: number
  total_tokens: number
  cost_cny: number
}

export interface DailyTrend {
  date: string
  total_tokens: number
  cost_cny: number
  call_count: number
}

export interface LogRow {
  id: string
  action_name: string
  caller: string
  model_name: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cached_tokens: number
  cost_cny: number
  estimated?: number
  created_at: string
}

