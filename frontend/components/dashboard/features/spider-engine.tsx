"use client"

import { useState } from "react"
import { Play, XCircle, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useCrawlerTaskStore } from "@/store/crawler-task-store"
import { toast } from "sonner"
import { PlatformSessionBar, type PlatformSessionItem } from "@/components/command-center/drawers/platform-session-bar"
import { MAIN_API_BASE } from "@/lib/platform-auth"

interface SpiderEngineProps {
  onTaskStarted: () => void
}

/**
 * 蜘蛛引擎 · 单平台调试表单。
 * 注：统一批量分发已迁移至「全链路指挥中心 · 抓取策略」，此处仅保留单平台精细调试能力。
 * 会话状态与生命周期管理直接复用「全链路指挥中心 · 平台抓取」的 PlatformSessionBar 组件与接口体系。
 */
export function SpiderEngine({ onTaskStarted }: SpiderEngineProps) {
  const addTask = useCrawlerTaskStore(state => state.addTask)
  const [sessions, setSessions] = useState<PlatformSessionItem[] | null>(null)
  const [loading, setLoading] = useState(false)

  const [keyword, setKeyword] = useState("")
  const [city, setCity] = useState("北京")
  const [salary, setSalary] = useState("不限")
  const [startPage, setStartPage] = useState("1")
  const [targetJobs, setTargetJobs] = useState("30")
  const [xhsSortBy, setXhsSortBy] = useState("general")

  const [platform, setPlatform] = useState<"boss" | "liepin" | "51job" | "xiaohongshu" | "zhilian">("boss")

  const isPlatformLoggedIn = (p: string) => {
    const item = sessions?.find(s => s.platform === p || (p === "xiaohongshu" && s.platform === "xhs"))
    return item ? (item.state === "healthy" || item.state === "degraded") : false
  }

  // 🌟 单次抓取严格限制为小批量（上限 50 个岗位），输入超过 50 自动截断并告警
  const handleTargetJobsChange = (val: string) => {
    if (val === "") {
      setTargetJobs("")
      return
    }
    const num = parseInt(val, 10)
    if (isNaN(num)) return
    if (num > 50) {
      setTargetJobs("50")
      toast.warning("单次任务抓取上限为 50 个岗位")
    } else if (num < 1) {
      setTargetJobs("1")
    } else {
      setTargetJobs(String(num))
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    // 🌟 函数级防抖锁：防止连续点击导致多次触发
    if (loading) return

    // 🌟 严格收口登录门禁：未通过探测直接拦截提交并红字提醒
    if (sessions && !isPlatformLoggedIn(platform)) {
      toast.error(`请先完成 ${platform.toUpperCase()} 平台登录授权！`)
      return
    }
    if (!isPlatformLoggedIn(platform)) {
      toast.error(`暂无 ${platform} 的有效登录态，请先完成上方授权！`)
      return
    }

    if (!keyword) {
      toast.error("请输入关键词！")
      return
    }

    // 🌟 参数边界约束：起始页 >= 1，目标抓取数 1-50（单次任务上限 50）
    const parsedPage = Math.max(1, parseInt(startPage, 10) || 1)
    const rawTarget = parseInt(targetJobs, 10) || 30
    if (rawTarget > 50) {
      toast.error("单次抓取任务目标数量上限为 50 个！")
      return
    }
    const parsedTarget = Math.min(50, Math.max(1, rawTarget))

    setLoading(true)
    try {
      const res = await fetch(`${MAIN_API_BASE}/v1/crawlers/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          platform,
          keyword,
          city,
          salary,
          start_page: parsedPage,
          target_jobs: parsedTarget,
          sort_by: platform === "xiaohongshu" ? xhsSortBy : undefined
        })
      })

      if (res.ok) {
        const data = await res.json()
        toast.success(data.message || "抓取任务已启动！")
        // 注册到全局状态库
        addTask({
          id: data.task_id,
          platform: platform as 'liepin' | 'boss' | '51job' | 'xiaohongshu' | 'zhilian',
          keyword,
          city,
          salary,
          targetJobs: parsedTarget
        })

        // 通知父组件先切换到日志 Tab，确保终端组件被挂载
        onTaskStarted()
      } else {
        const err = await res.json()
        toast.error(`启动失败: ${err.detail || "未知错误"}`)
      }
    } catch {
      toast.error("网络异常，无法连接到爬虫调度中心")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-full bg-gray-50 overflow-y-auto">
      <div className="p-4 space-y-6">

        {/* 会话状态与生命周期 - 直接复用全链路中心组件与状态流 */}
        <PlatformSessionBar onSessionsChange={setSessions} gridClassName="grid-cols-2" />

        {/* Configuration Form */}
        <form onSubmit={handleSubmit} className="bg-white p-4 rounded-xl border border-gray-100 shadow-sm space-y-5">
          <div className="space-y-3">
            <Label>目标平台</Label>
            <RadioGroup value={platform} onValueChange={(v) => setPlatform(v as "boss" | "liepin" | "51job" | "xiaohongshu" | "zhilian")} className="flex gap-4">
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="boss" id="r-boss" />
                <Label htmlFor="r-boss">BOSS</Label>
              </div>
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="zhilian" id="r-zhilian" />
                <Label htmlFor="r-zhilian">智联</Label>
              </div>
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="liepin" id="r-liepin" />
                <Label htmlFor="r-liepin">猎聘</Label>
              </div>
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="51job" id="r-51job" />
                <Label htmlFor="r-51job">51job</Label>
              </div>
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="xiaohongshu" id="r-xhs" />
                <Label htmlFor="r-xhs">小红书</Label>
              </div>
            </RadioGroup>
          </div>

          <div className="space-y-3">
            <Label htmlFor="keyword">搜索关键词 <span className="text-red-500">*</span></Label>
            <Input id="keyword" value={keyword} onChange={e => setKeyword(e.target.value)} placeholder="如：产品经理、前端开发" required />
          </div>

          {platform !== "xiaohongshu" && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="city">城市</Label>
                  <Input id="city" value={city} onChange={e => setCity(e.target.value)} placeholder="如：北京、全国" />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="salary">薪资范围</Label>
                  <Select value={salary} onValueChange={setSalary}>
                    <SelectTrigger id="salary">
                      <SelectValue placeholder="不限" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="不限">不限</SelectItem>
                      {platform === 'zhilian' ? (
                        <>
                          <SelectItem value="4K以下">4K以下</SelectItem>
                          <SelectItem value="4K-6K">4K-6K</SelectItem>
                          <SelectItem value="6K-8K">6K-8K</SelectItem>
                          <SelectItem value="8K-10K">8K-10K</SelectItem>
                          <SelectItem value="10K-15K">10K-15K</SelectItem>
                          <SelectItem value="15K-25K">15K-25K</SelectItem>
                          <SelectItem value="25K-35K">25K-35K</SelectItem>
                          <SelectItem value="35K-50K">35K-50K</SelectItem>
                          <SelectItem value="50K以上">50K以上</SelectItem>
                        </>
                      ) : platform === '51job' ? (
                        <>
                          <SelectItem value="8千以下">8千以下</SelectItem>
                          <SelectItem value="0.8-1万">0.8-1万</SelectItem>
                          <SelectItem value="1-1.5万">1-1.5万</SelectItem>
                          <SelectItem value="1.5-2万">1.5-2万</SelectItem>
                          <SelectItem value="2-3万">2-3万</SelectItem>
                          <SelectItem value="3-4万">3-4万</SelectItem>
                          <SelectItem value="4-5万">4-5万</SelectItem>
                        </>
                      ) : (
                        <>
                          <SelectItem value="3K以下">3K以下</SelectItem>
                          <SelectItem value="3-5K">3-5K</SelectItem>
                          <SelectItem value="5-10K">5-10K</SelectItem>
                          <SelectItem value="10-20K">10-20K</SelectItem>
                          <SelectItem value="20-50K">20-50K</SelectItem>
                          <SelectItem value="50K以上">50K以上</SelectItem>
                        </>
                      )}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="startPage">起始页码</Label>
                  <Input id="startPage" type="number" min={1} value={startPage} onChange={e => setStartPage(e.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="targetJobs">目标抓取数 (上限50)</Label>
                  <Input
                    id="targetJobs"
                    type="number"
                    min={1}
                    max={50}
                    value={targetJobs}
                    onChange={e => handleTargetJobsChange(e.target.value)}
                  />
                </div>
              </div>
            </>
          )}

          {platform === "xiaohongshu" && (
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="xhsSortBy">排序依据</Label>
                <Select value={xhsSortBy} onValueChange={setXhsSortBy}>
                  <SelectTrigger id="xhsSortBy">
                    <SelectValue placeholder="综合" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="general">综合</SelectItem>
                    <SelectItem value="time_descending">最新</SelectItem>
                    <SelectItem value="popularity_descending">最多点赞</SelectItem>
                    <SelectItem value="collects_descending">最多收藏</SelectItem>
                    <SelectItem value="comments_descending">最多评论</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="targetJobs">目标抓取数 (上限50)</Label>
                <Input
                  id="targetJobs"
                  type="number"
                  min={1}
                  max={50}
                  value={targetJobs}
                  onChange={e => handleTargetJobsChange(e.target.value)}
                />
              </div>
            </div>
          )}

          <div className="pt-2">
            <Button
              type="submit"
              className="w-full bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 cursor-pointer"
              disabled={loading || !sessions || !isPlatformLoggedIn(platform)}
            >
              {loading ? (
                <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> 启动引擎中...</>
              ) : !sessions ? (
                <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> 检测授权状态中...</>
              ) : !isPlatformLoggedIn(platform) ? (
                <><XCircle className="mr-2 h-4 w-4" /> 暂无登录态，请先完成上方授权</>
              ) : (
                <><Play className="mr-2 h-4 w-4" /> 启动全量抓取</>
              )}
            </Button>
          </div>
        </form>

      </div>
    </div>
  )
}
