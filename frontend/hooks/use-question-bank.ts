import { useState, useMemo, useEffect } from "react"
import { API_BASE } from "@/lib/api"
import { toast } from "@/hooks/use-toast"

export type QuestionItem = {
  record_id: string
  question: string
  mastery_status: string
  golden_answer: string
  ai_demo: string
  source: string
  tags: string
  related_jobs: string[]
  question_type: string
  industry: string
  job_group: string | string[]
  company_and_job: string
  interview_stage: string
  original_text: string
  frequency: number
}

const MASTERY_CYCLE = ["⚪ 已收录", "🔴 未掌握", "🟡 练习中", "🟢 已掌握"]

export function useQuestionBank(activeTab: string) {
  const [questions, setQuestions] = useState<QuestionItem[]>([])
  const [isLoadingQs, setIsLoadingQs] = useState(false)
  
  const [activeDrillQuestion, setActiveDrillQuestion] = useState<QuestionItem | null>(null)
  const [expandedDemo, setExpandedDemo] = useState<Record<string, boolean>>({})
  const [expandedOriginal, setExpandedOriginal] = useState<Record<string, boolean>>({})
  const [savingMap, setSavingMap] = useState<Record<string, boolean>>({})
  const [sourceFilter, setSourceFilter] = useState<"全部" | "⚔️ 真实复盘" | "🌐 简历专项预测">("全部")


  // 按来源筛选
  const filteredQuestions = useMemo(() => {
    return questions.filter(q => {
      if (sourceFilter === "全部") return true
      if (sourceFilter === "⚔️ 真实复盘") return q.source?.includes("真实战场复盘")
      return q.source?.includes("简历专项预测")
    })
  }, [questions, sourceFilter])

  // 同题合并
  const groupedQuestions = useMemo(() => {
    const map = new Map<string, QuestionItem[]>()
    filteredQuestions.forEach(q => {
      const key = (q.question || "").trim()
      if (!key) return
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(q)
    })
    // 按该题下记录数量降序，使热门多视角题优先呈现
    return Array.from(map.entries()).sort((a, b) => b[1].length - a[1].length)
  }, [filteredQuestions])

  const fetchQuestions = async () => {
    setIsLoadingQs(true)
    try {
      const res = await fetch(`${API_BASE}/api/questions`)
      const data = await res.json()
      if (data?.status === "success") {
        setQuestions(data.items || [])
      } else {
        setQuestions([])
        console.warn("拉取面经库失败:", data?.error)
      }
    } catch (e) {
      console.error("面经库请求异常:", e)
      setQuestions([])
    } finally {
      setIsLoadingQs(false)
    }
  }

  // 自动加载
  useEffect(() => {
    if (activeTab === "question_bank" && questions.length === 0 && !isLoadingQs) {
      fetchQuestions()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab])

  const updateQuestionField = async (
    record_id: string,
    patch: Partial<Pick<QuestionItem, "mastery_status" | "golden_answer" | "ai_demo">>
  ) => {
    setSavingMap(s => ({ ...s, [record_id]: true }))
    try {
      const res = await fetch(`${API_BASE}/api/questions/${record_id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      })
      const data = await res.json()
      if (!res.ok || data.status !== "success") throw new Error(data?.detail || "更新失败")
      setQuestions(prev => prev.map(q => q.record_id === record_id ? { ...q, ...patch } : q))
    } catch (e: any) {
      toast({
        title: "❌ 同步失败",
        description: e?.message || String(e),
        variant: "destructive",
      })
    } finally {
      setSavingMap(s => ({ ...s, [record_id]: false }))
    }
  }

  const deleteQuestion = async (record_id: string) => {
    setSavingMap(s => ({ ...s, [record_id]: true }))
    try {
      const res = await fetch(`${API_BASE}/api/questions/${record_id}`, {
        method: "DELETE",
      })
      const data = await res.json()
      if (!res.ok || data.status !== "success") throw new Error(data?.detail || "删除失败")
      setQuestions(prev => prev.filter(q => q.record_id !== record_id))
      toast({
        title: "🗑️ 题目已删除",
        description: "该道真题卡片已从云端飞书题库永久移除。",
      })
    } catch (e: any) {
      toast({
        title: "❌ 删除失败",
        description: e?.message || String(e),
        variant: "destructive",
      })
    } finally {
      setSavingMap(s => ({ ...s, [record_id]: false }))
    }
  }

  const cycleMastery = (q: QuestionItem) => {
    const idx = MASTERY_CYCLE.findIndex(m => q.mastery_status?.includes(m.split(" ")[0]))
    const next = MASTERY_CYCLE[(idx + 1 + MASTERY_CYCLE.length) % MASTERY_CYCLE.length]
    updateQuestionField(q.record_id, { mastery_status: next })
  }

  const masteryColor = (status: string) => {
    if (!status) return "border-gray-200 bg-gray-50 text-gray-500"
    if (status.includes("🔴") || status.includes("未掌握")) return "border-red-200 bg-red-50 text-red-600 hover:bg-red-100"
    if (status.includes("🟡") || status.includes("练习中")) return "border-amber-200 bg-amber-50 text-amber-600 hover:bg-amber-100"
    if (status.includes("🟢") || status.includes("已掌握")) return "border-green-200 bg-green-50 text-green-600 hover:bg-green-100"
    return "border-gray-200 bg-gray-50 text-gray-500 hover:bg-gray-100"
  }

  return {
    questions,
    setQuestions,
    isLoadingQs,
    activeDrillQuestion,
    setActiveDrillQuestion,
    expandedDemo,
    setExpandedDemo,
    expandedOriginal,
    setExpandedOriginal,
    savingMap,
    sourceFilter,
    setSourceFilter,
    filteredQuestions,
    groupedQuestions,
    fetchQuestions,
    updateQuestionField,
    deleteQuestion,
    cycleMastery,
    masteryColor
  }
}
