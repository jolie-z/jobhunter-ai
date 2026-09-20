"use client"

/**
 * 期望职位编辑弹窗（共享组件 —— boss-tab 与 agent-tab 同源，改一处两边生效）
 *
 * 照搬 BOSS 官网表单：
 *  全职：期望职位(单选) + 期望行业(≤3) + 薪资 + 工作城市 + 其他城市
 *  兼职：期望兼职职位(≤5) + 期望行业(≤3) + 兼职偏好 + 兼职时间 + 工作城市 + 其他城市
 * 上限：全职 3 条 / 兼职 1 条（新增时校验；编辑现有条目不校验）
 *
 * 对外契约：onSave 返回 BOSS 标准条目（兼职含 position 聚合串 + positions 数组）
 */

import { useEffect, useState } from "react"
import { createPortal } from "react-dom"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { JobTitleSelector } from "@/components/ui/job-title-selector"
import { IndustrySelector } from "@/components/ui/industry-selector"
import { CitySelector } from "@/components/ui/city-selector"
import { OtherCitySelector } from "@/components/ui/other-city-selector"
import { SalarySelector } from "@/components/ui/salary-selector"
import {
  formatSalaryRange,
  parseBossSalaryFormat,
} from "@/lib/salary-formatter"

export interface ExpectationItem {
  jobType?: string
  position?: string
  positions?: string[]
  industries?: string[]
  salary?: string
  city?: string
  otherCities?: string[]
  parttime_preference?: string[]
  parttime_time?: string[]
}

interface ExpectationFormState {
  jobType: "fulltime" | "parttime"
  position: string
  positions: string[]
  industries: string[]
  salaryMin: string
  salaryMax: string
  city: string
  otherCities: string[]
  parttime_preference: string[]
  parttime_time: string[]
}

interface ExpectationEditorProps {
  open: boolean
  editing: boolean            // true=编辑现有条目；false=新增（校验上限）
  fulltimeCount: number       // 现有全职条数（新增校验用）
  parttimeCount: number       // 现有兼职条数
  initial?: ExpectationItem   // 编辑预填（原始条目）
  onOpenChange: (open: boolean) => void
  onSave: (item: ExpectationItem) => void
}

const EMPTY_FORM: ExpectationFormState = {
  jobType: "fulltime",
  position: "",
  positions: [],
  industries: [],
  salaryMin: "",
  salaryMax: "",
  city: "",
  otherCities: [],
  parttime_preference: [],
  parttime_time: [],
}

// 条目 → 表单（编辑预填：salary 拆分、city 逗号拆分、兼职 position 聚合串 → positions）
function itemToForm(
  item: ExpectationItem,
  parsedSalary?: { min: string | null; max: string | null } | null
): ExpectationFormState {
  const isPt = (item.jobType || "fulltime") === "parttime"
  if (isPt) {
    return {
      jobType: "parttime",
      position: "",
      positions: item.positions || (item.position ? item.position.split("、") : []),
      industries: item.industries || [],
      salaryMin: "",
      salaryMax: "",
      city: item.city || "",
      otherCities: item.otherCities || [],
      parttime_preference: item.parttime_preference || [],
      parttime_time: item.parttime_time || [],
    }
  }
  // 全职：使用解析后的薪资或手动拆分
  let salaryMin = parsedSalary?.min || ""
  let salaryMax = parsedSalary?.max || ""
  
  if (!parsedSalary && item.salary) {
    // Fallback: 如果 parseBossSalaryFormat 失败，尝试简单拆分
    const parts = item.salary.split("-")
    if (parts.length === 2) { salaryMin = parts[0]; salaryMax = parts[1] }
    else { salaryMin = item.salary }
  }
  
  let city = item.city || ""
  let otherCities: string[] = item.otherCities || []
  if (city.includes(",") || city.includes("，")) {
    const cityParts = city.split(/[,，]\s*/).map((c) => c.trim()).filter(Boolean)
    city = cityParts[0] || ""
    otherCities = [...new Set([...cityParts.slice(1), ...otherCities])]
  }
  return {
    jobType: "fulltime",
    position: item.position || "",
    positions: [],
    industries: item.industries || [],
    salaryMin, salaryMax,
    city, otherCities,
    parttime_preference: [],
    parttime_time: [],
  }
}

// 表单 → BOSS 标准条目（带薪资格式转换）
function formToItem(form: ExpectationFormState): ExpectationItem {
  if (form.jobType === "parttime") {
    return {
      jobType: "parttime",
      positions: form.positions,
      position: form.positions.join("、"),
      industries: form.industries,
      salary: "",
      city: form.city,
      otherCities: form.otherCities,
      parttime_preference: form.parttime_preference,
      parttime_time: form.parttime_time,
    }
  }
  // 🐛 Fix #1: Use normalized salary range
  const salaryText = formatSalaryRange(form.salaryMin, form.salaryMax)
  
  return {
    jobType: "fulltime",
    position: form.position,
    industries: form.industries,
    salary: salaryText,
    city: form.city,
    otherCities: form.otherCities, // 🐛 Fix #2: Ensure array preserved
  }
}

// ===== 兼职偏好/时间选项（来自 BOSS 直聘官方平台，与 boss-tab 原实现一致） =====
const PARTTIME_PREF_GROUPS: { label: string; options: string[] }[] = [
  { label: "兼职类型", options: ["长期兼职", "短期兼职", "节假日兼职", "周末兼职", "工作日兼职", "暑假兼职", "寒假兼职"] },
  { label: "班次/时间段", options: ["固定班次", "排班制", "24小时倒班", "晚间兼职", "夜班", "小时工"] },
  { label: "薪资结算方式", options: ["完工结", "日结", "周结", "半月结", "月结"] },
  { label: "工作内容", options: ["室外工作", "远程办公", "体力活", "销售"] },
  { label: "福利待遇", options: ["有提成", "包吃", "餐补", "加班补贴", "夜班补贴"] },
]
const PARTTIME_TIME_GROUPS: { label: string; options: string[] }[] = [
  { label: "工作时间", options: ["周末节假日", "工作日", "接受轮班", "时间灵活"] },
  { label: "工作时段", options: ["时间灵活", "早班", "午班", "晚班", "夜班"] },
  { label: "每周工作天数", options: ["时间灵活", "5天及以上", "3-4天", "2-3天", "1-2天"] },
]

function MultiChoicePopup({ title, groups, value, onChange, onClose }: {
  title: string
  groups: { label: string; options: string[] }[]
  value: string[]
  onChange: (next: string[]) => void
  onClose: () => void
}) {
  const toggle = (opt: string) => {
    onChange(value.includes(opt) ? value.filter((x) => x !== opt) : [...value, opt])
  }
  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center" style={{ pointerEvents: "auto" }}>
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative z-10 w-[560px] max-h-[80vh] rounded-lg bg-white shadow-xl flex flex-col">
        <div className="flex items-center justify-between border-b px-5 py-3">
          <h3 className="text-base font-medium text-gray-900">{title}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {groups.map((group) => (
            <div key={group.label}>
              <span className="text-xs text-gray-400 mb-1.5 block">{group.label}</span>
              <div className="flex flex-wrap gap-1.5">
                {group.options.map((opt) => {
                  const selected = value.includes(opt)
                  return (
                    <button
                      key={opt}
                      type="button"
                      onClick={() => toggle(opt)}
                      className={`px-2.5 py-1 rounded-md text-xs border transition-colors ${
                        selected
                          ? "border-[#00beab] bg-[#00beab]/10 text-[#00beab]"
                          : "border-gray-200 text-gray-600 hover:border-gray-300"
                      }`}
                    >
                      {opt}
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
        <div className="border-t px-5 py-3 flex items-center justify-between">
          <span className="text-xs text-gray-400">
            {value.length > 0 ? `已选 ${value.length} 项` : "未选择"}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => onChange([])}
              className="rounded-md border border-gray-200 px-4 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
            >
              清空
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md bg-[#00beab] px-4 py-1.5 text-sm text-white hover:bg-[#00a99a]"
            >
              确定
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

function ChipsTrigger({ values, placeholder, onClick }: { values: string[]; placeholder: string; onClick: () => void }) {
  return (
    <div
      className="flex min-h-[40px] w-full cursor-pointer items-center rounded-md border border-input bg-background px-3 py-2 text-sm hover:border-[#00beab]"
      onClick={onClick}
    >
      {values.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {values.map((item) => (
            <span key={item} className="inline-flex items-center rounded bg-[#00beab]/10 px-2 py-0.5 text-xs text-[#00beab]">
              {item}
            </span>
          ))}
        </div>
      ) : (
        <span className="text-muted-foreground">{placeholder}</span>
      )}
    </div>
  )
}

export function ExpectationEditor({ open, editing, fulltimeCount, parttimeCount, initial, onOpenChange, onSave }: ExpectationEditorProps) {
  const [form, setForm] = useState<ExpectationFormState>(EMPTY_FORM)
  const [error, setError] = useState("")
  const [prefPopupOpen, setPrefPopupOpen] = useState(false)
  const [timePopupOpen, setTimePopupOpen] = useState(false)

  // 打开时重置表单：编辑预填 / 新增空表单
  useEffect(() => {
    if (!open) return
    const parsed = editing && initial ? parseBossSalaryFormat(initial.salary || '') : null
    setForm({
      ...EMPTY_FORM,
      ...(editing && initial 
        ? itemToForm(initial, parsed)
        : EMPTY_FORM),
    })
    setError("")
  }, [open, editing, initial])

  const isParttime = form.jobType === "parttime"
  // 满额判断按当前表单类型独立生效（全职满 3 不影响兼职页，兼职满 1 不影响全职页）
  const fulltimeFull = !editing && form.jobType === "fulltime" && fulltimeCount >= 3
  const parttimeFull = !editing && form.jobType === "parttime" && parttimeCount >= 1
  const saveDisabled = fulltimeFull || parttimeFull

  const handleSave = () => {
    if (!editing && isParttime && form.positions.length === 0) {
      setError("请至少选择 1 个兼职职位")
      return
    }
    setError("")
    onSave(formToItem(form))
  }

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          if (!o) setPrefPopupOpen(false)
          onOpenChange(o)
        }}
      >
        <DialogContent
          className="max-w-[520px] max-h-[90vh] overflow-y-auto"
          onInteractOutside={(e) => {
            if (prefPopupOpen || timePopupOpen) e.preventDefault()
          }}
          onPointerDownOutside={(e) => {
            if (prefPopupOpen || timePopupOpen) e.preventDefault()
          }}
        >
          <DialogHeader>
            <DialogTitle>{editing ? "编辑求职期望" : "添加求职期望"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {/* 求职类型 */}
            <div>
              <label className="text-sm font-medium mb-1.5 block">求职类型</label>
              <div className="flex gap-2">
                {(["fulltime", "parttime"] as const).map((type) => (
                  <button
                    key={type}
                    type="button"
                    onClick={() => setForm({ ...form, jobType: type, position: "", positions: form.positions || [] })}
                    className={`px-4 py-1.5 rounded-md text-sm border transition-colors ${
                      form.jobType === type
                        ? "border-[#00beab] bg-[#00beab]/10 text-[#00beab] font-medium"
                        : "border-gray-200 text-gray-600 hover:border-gray-300"
                    }`}
                  >
                    {type === "fulltime" ? "全职" : "兼职"}
                  </button>
                ))}
              </div>
            </div>

            {isParttime ? (
              <>
                {/* ===== 兼职：期望职位（多选，最多5个） ===== */}
                <div>
                  <label className="text-sm font-medium mb-1.5 block">
                    期望兼职职位 <span className="text-red-500">*</span> <span className="text-gray-400 font-normal">（最多选5个）</span>
                  </label>
                  {form.positions.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mb-2">
                      {form.positions.map((pos, i) => (
                        <span key={pos + i} className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-[#00beab]/10 text-[#00beab] text-sm border border-[#00beab]/30">
                          {pos}
                          <button
                            type="button"
                            onClick={() => setForm({ ...form, positions: form.positions.filter((_, j) => j !== i) })}
                            className="hover:text-red-500 transition-colors"
                          >
                            ×
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                  {form.positions.length < 5 && (
                    <JobTitleSelector
                      value=""
                      onChange={(value) => {
                        if (value && !form.positions.includes(value)) {
                          setForm({ ...form, positions: [...form.positions, value] })
                        }
                      }}
                      placeholder="点击选择兼职职位"
                      jobType="parttime"
                    />
                  )}
                </div>

                {/* 期望行业 */}
                <div>
                  <label className="text-sm font-medium mb-1.5 block">期望行业（最多选3个）</label>
                  <IndustrySelector
                    value={form.industries}
                    onChange={(value) => setForm({ ...form, industries: value })}
                    placeholder="行业不限"
                    max={3}
                  />
                </div>

                {/* 兼职偏好 */}
                <div>
                  <label className="text-sm font-medium mb-1.5 block">兼职偏好</label>
                  <ChipsTrigger values={form.parttime_preference} placeholder="请选择兼职偏好" onClick={() => setPrefPopupOpen(true)} />
                </div>

                {/* 兼职时间 */}
                <div>
                  <label className="text-sm font-medium mb-1.5 block">兼职时间</label>
                  <ChipsTrigger values={form.parttime_time} placeholder="请选择兼职时间" onClick={() => setTimePopupOpen(true)} />
                </div>
              </>
            ) : (
              <>
                {/* ===== 全职：期望职位（单选） ===== */}
                <div>
                  <label className="text-sm font-medium mb-1.5 block">期望职位</label>
                  <JobTitleSelector
                    value={form.position}
                    onChange={(value) => setForm({ ...form, position: value })}
                    placeholder="请选择期望职位"
                    jobType="fulltime"
                  />
                </div>

                {/* 期望行业（最多3个） */}
                <div>
                  <label className="text-sm font-medium mb-1.5 block">期望行业（最多选3个）</label>
                  <IndustrySelector
                    value={form.industries}
                    onChange={(value) => setForm({ ...form, industries: value })}
                    placeholder="行业不限"
                    max={3}
                  />
                </div>

                {/* 薪资要求 */}
                <div>
                  <label className="text-sm font-medium mb-1.5 block">薪资要求</label>
                  <SalarySelector
                    valueMin={form.salaryMin}
                    valueMax={form.salaryMax}
                    onChangeMin={(v) => setForm({ ...form, salaryMin: v })}
                    onChangeMax={(v) => setForm({ ...form, salaryMax: v })}
                  />
                </div>
              </>
            )}

            {/* 工作城市 */}
            <div>
              <label className="text-sm font-medium mb-1.5 block">工作城市</label>
              <CitySelector
                value={form.city}
                onChange={(value) => setForm({ ...form, city: value })}
                placeholder="请选择工作城市"
              />
            </div>

            {/* 其他感兴趣的城市（选填） */}
            <div>
              <label className="text-sm font-medium mb-1.5 block">
                其他感兴趣的城市 <span className="text-gray-400 font-normal">（选填）</span>
              </label>
              <OtherCitySelector
                value={form.otherCities}
                onChange={(value) => setForm({ ...form, otherCities: value })}
                placeholder="选择其他感兴趣城市"
              />
            </div>

            {/* 校验错误（内联红字，替代 toast） */}
            {error && <div className="text-xs text-red-500">{error}</div>}

            {/* 操作按钮 */}
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={() => onOpenChange(false)} className="rounded-md border border-gray-200 px-4 py-1.5 text-sm text-gray-600 hover:bg-gray-50">
                取消
              </button>
              <button
                type="button"
                disabled={saveDisabled}
                onClick={handleSave}
                className={`rounded-md px-4 py-1.5 text-sm transition-colors ${
                  saveDisabled ? "bg-gray-300 text-gray-500 cursor-not-allowed" : "bg-[#00beab] hover:bg-[#00a99a] text-white"
                }`}
              >
                {fulltimeFull ? "全职已满" : parttimeFull ? "兼职已满" : editing ? "完成" : "添加"}
              </button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {prefPopupOpen && (
        <MultiChoicePopup
          title="兼职偏好"
          groups={PARTTIME_PREF_GROUPS}
          value={form.parttime_preference}
          onChange={(v) => setForm({ ...form, parttime_preference: v })}
          onClose={() => setPrefPopupOpen(false)}
        />
      )}
      {timePopupOpen && (
        <MultiChoicePopup
          title="兼职时间"
          groups={PARTTIME_TIME_GROUPS}
          value={form.parttime_time}
          onChange={(v) => setForm({ ...form, parttime_time: v })}
          onClose={() => setTimePopupOpen(false)}
        />
      )}
    </>
  )
}
