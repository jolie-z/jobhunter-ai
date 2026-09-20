"use client"

import { useState, useEffect } from "react"
import { Loader2, Zap } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Checkbox } from "@/components/ui/checkbox"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useCrawlerTaskStore } from "@/store/crawler-task-store"
import { toast } from "sonner"

const API_BASE_URL = "http://127.0.0.1:8000/api"

const ALL_PLATFORMS = [
  { id: "boss", label: "BOSS直聘" },
  { id: "liepin", label: "猎聘" },
  { id: "51job", label: "前程无忧" },
  { id: "zhilian", label: "智联招聘" },
  { id: "xiaohongshu", label: "小红书" },
] as const

interface BatchDispatchFormProps {
  // 分发成功后的回调（如切换到日志流 Tab）
  onDispatched?: () => void
}

/**
 * 统一批量分发表单：一份搜索单 → 多平台同时抓取。
 * 从 spider-engine 抽取而来，现作为「指挥中心 · 抓取策略」的核心输入区。
 * 行为不变：POST /api/v1/crawlers/dispatch，子任务注册到 crawler-task-store。
 */
export function BatchDispatchForm({ onDispatched }: BatchDispatchFormProps) {
  const addTask = useCrawlerTaskStore(state => state.addTask)

  const [dispatchLoading, setDispatchLoading] = useState(false)
  const [dKeyword, setDKeyword] = useState("")
  const [dCity, setDCity] = useState("广州")
  const [dSalary, setDSalary] = useState("不限")
  const [dTargetJobs, setDTargetJobs] = useState("20")
  const [dPlatforms, setDPlatforms] = useState<string[]>(["boss", "liepin", "51job", "zhilian", "xiaohongshu"])
  const [salaryTiers, setSalaryTiers] = useState<string[]>([])

  // 拉取标准薪资档位
  useEffect(() => {
    fetch(`${API_BASE_URL}/v1/crawlers/salary-tiers`)
      .then(res => res.ok ? res.json() : null)
      .then(data => { if (data?.tiers) setSalaryTiers(data.tiers) })
      .catch(() => {})
  }, [])

  const togglePlatform = (id: string) => {
    setDPlatforms(prev =>
      prev.includes(id) ? prev.filter(p => p !== id) : [...prev, id]
    )
  }

  const handleDispatch = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!dKeyword.trim()) {
      toast.error("请输入搜索关键词！")
      return
    }
    if (dPlatforms.length === 0) {
      toast.error("请至少勾选一个平台！")
      return
    }

    setDispatchLoading(true)
    try {
      const res = await fetch(`${API_BASE_URL}/v1/crawlers/dispatch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          keyword: dKeyword.trim(),
          city: dCity,
          salary: dSalary,
          target_jobs: parseInt(dTargetJobs) || 20,
          platforms: dPlatforms,
          run_type: "now",
        })
      })

      if (res.ok) {
        const data = await res.json()
        toast.success(data.message || "批量分发已启动！")

        for (const sub of data.sub_tasks) {
          addTask({
            id: sub.task_id,
            platform: sub.platform as 'liepin' | 'boss' | '51job' | 'xiaohongshu' | 'zhilian',
            keyword: sub.keyword,
            city: sub.city || dCity,
            salary: sub.salary || dSalary,
            targetJobs: sub.target_jobs,
          })
        }

        onDispatched?.()
      } else {
        const err = await res.json()
        toast.error(`分发失败: ${err.detail || "未知错误"}`)
      }
    } catch (e) {
      toast.error("网络异常，无法连接到爬虫调度中心")
    } finally {
      setDispatchLoading(false)
    }
  }

  return (
    <form onSubmit={handleDispatch} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="d-keyword">搜索关键词 <span className="text-red-500">*</span></Label>
        <Input id="d-keyword" value={dKeyword} onChange={e => setDKeyword(e.target.value)} placeholder="如：AGENT、产品经理" required />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="d-city">城市</Label>
          <Input id="d-city" value={dCity} onChange={e => setDCity(e.target.value)} placeholder="如：广州、全国" />
        </div>
        <div className="space-y-2">
          <Label htmlFor="d-salary">薪资范围</Label>
          <Select value={dSalary} onValueChange={setDSalary}>
            <SelectTrigger id="d-salary">
              <SelectValue placeholder="不限" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="不限">不限</SelectItem>
              {salaryTiers.map(tier => (
                <SelectItem key={tier} value={tier}>{tier}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="d-target">每平台抓取数</Label>
        <Input id="d-target" type="number" min={1} value={dTargetJobs} onChange={e => setDTargetJobs(e.target.value)} />
      </div>

      <div className="space-y-2">
        <Label>目标平台</Label>
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          {ALL_PLATFORMS.map(p => (
            <label key={p.id} className="flex items-center gap-2 cursor-pointer select-none">
              <Checkbox
                checked={dPlatforms.includes(p.id)}
                onCheckedChange={() => togglePlatform(p.id)}
              />
              <span className="text-sm text-gray-700">{p.label}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="pt-1">
        <Button
          type="submit"
          className="w-full bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700"
          disabled={dispatchLoading || dPlatforms.length === 0}
        >
          {dispatchLoading ? (
            <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> 分发中...</>
          ) : (
            <><Zap className="mr-2 h-4 w-4" /> 一键启动 ({dPlatforms.length} 个平台)</>
          )}
        </Button>
      </div>
    </form>
  )
}
