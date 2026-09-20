/**
 * Zhilian Tab 专属选择器组件（机械搬迁自 zhilian-tab.tsx，行为零变化）
 * 年月选择器/城市级联/城市下拉/年月输入 —— 模拟智联官网 ivu-date-picker 与 s-cascader 交互
 */
"use client"

import { useState, useRef } from "react"
import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"
import { ZHILIAN_MONTHS, ZHILIAN_CITIES_FULL, ZHILIAN_PROVINCES } from "@/lib/zhilian-options"
import type { ZhilianProvinceFull, ZhilianCityWithDistricts } from "@/lib/zhilian-options"
import { PRIMARY } from "./constants"

// 年月选择器 - 模拟智联 ivu-date-picker：先选年（十年网格）再选月（fixed定位，兼容弹窗）
export function YearMonthPicker({ year, month, onYearChange, onMonthChange, disabled = false, minYear, minMonth }: {
  year: string
  month: string
  onYearChange: (y: string) => void
  onMonthChange: (m: string) => void
  disabled?: boolean
  minYear?: string   // 最小可选年（离职时间需大于入职时间）
  minMonth?: string  // 最小可选月
}) {
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState<"year" | "month">("year")
  const [decadeStart, setDecadeStart] = useState(2020)
  const [selYear, setSelYear] = useState("")
  const [pos, setPos] = useState({ top: 0, left: 0 })
  const btnRef = useRef<HTMLButtonElement>(null)

  const displayText = year && month ? `${year}-${month.padStart(2, "0")}` : ""

  const toggleOpen = () => {
    if (disabled) return
    if (!open && btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect()
      setPos({ top: rect.bottom + 4, left: rect.left })
    }
    if (!open) {
      // 打开时：如果已有年份直接进入月选择，否则进入年选择
      const y = Number(year) || new Date().getFullYear()
      setDecadeStart(Math.floor(y / 10) * 10)
      if (year) { setSelYear(year); setStep("month") } else { setStep("year") }
    }
    setOpen(!open)
  }

  const years = Array.from({ length: 10 }, (_, i) => decadeStart + i)

  const isYearDisabled = (y: number) => {
    if (!minYear) return false
    return y < Number(minYear)
  }

  const isMonthDisabled = (m: number) => {
    if (!minYear || !minMonth) return false
    const y = Number(selYear)
    const minY = Number(minYear)
    const minM = Number(minMonth)
    if (y < minY) return true
    if (y === minY && m <= minM) return true
    return false
  }

  return (
    <div className="relative">
      <button
        ref={btnRef}
        type="button"
        onClick={toggleOpen}
        disabled={disabled}
        className={cn(
          "w-full h-9 px-3 text-sm border rounded-md text-left flex items-center justify-between",
          disabled ? "bg-gray-100 border-gray-200 cursor-not-allowed" : "bg-white",
          open ? "border-[#2A7BFF]" : "border-gray-300"
        )}
      >
        <span className={displayText ? "text-gray-900" : disabled ? "text-gray-300" : "text-gray-400"}>{displayText || "请选择"}</span>
        <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
      </button>
      {open && (
        <div className="fixed z-[200] bg-white border border-gray-200 rounded-lg shadow-lg p-3 w-[220px]" style={{ top: pos.top, left: pos.left }}>
          {step === "year" ? (
            <>
              {/* 年代导航 */}
              <div className="flex items-center justify-between mb-2">
                <button type="button" onClick={() => setDecadeStart(decadeStart - 10)} className="p-1 hover:bg-gray-100 rounded text-gray-500">
                  <span className="text-xs">{"<<"}</span>
                </button>
                <span className="text-sm font-medium text-gray-800">{decadeStart}年-{decadeStart + 9}年</span>
                <button type="button" onClick={() => setDecadeStart(decadeStart + 10)} className="p-1 hover:bg-gray-100 rounded text-gray-500">
                  <span className="text-xs">{">>"}</span>
                </button>
              </div>
              {/* 年网格 3列 */}
              <div className="grid grid-cols-3 gap-1">
                {years.map(y => (
                  <button
                    key={y}
                    type="button"
                    disabled={isYearDisabled(y)}
                    onClick={() => { setSelYear(String(y)); setStep("month") }}
                    className={cn(
                      "py-1.5 text-xs rounded transition-colors",
                      isYearDisabled(y) ? "text-gray-300 cursor-not-allowed" :
                      String(y) === year ? "text-white" : "text-gray-600 hover:bg-gray-100"
                    )}
                    style={String(y) === year && !isYearDisabled(y) ? { backgroundColor: PRIMARY } : {}}
                  >
                    {y}
                  </button>
                ))}
              </div>
            </>
          ) : (
            <>
              {/* 年标题 - 点击返回年选择 */}
              <div className="flex items-center justify-between mb-2">
                <button type="button" onClick={() => setStep("year")} className="p-1 hover:bg-gray-100 rounded text-gray-500">
                  <span className="text-xs">{"<<"}</span>
                </button>
                <button type="button" onClick={() => setStep("year")} className="text-sm font-medium text-gray-800 hover:text-[#2A7BFF]">
                  {selYear}年
                </button>
                <button type="button" onClick={() => { setSelYear(String(Number(selYear) + 1)); setDecadeStart(Math.floor((Number(selYear) + 1) / 10) * 10) }} className="p-1 hover:bg-gray-100 rounded text-gray-500">
                  <span className="text-xs">{">>"}</span>
                </button>
              </div>
              {/* 月网格 3列x4行 */}
              <div className="grid grid-cols-3 gap-1">
                {ZHILIAN_MONTHS.map(m => (
                  <button
                    key={m}
                    type="button"
                    disabled={isMonthDisabled(m)}
                    onClick={() => {
                      onYearChange(selYear)
                      onMonthChange(String(m))
                      setOpen(false)
                    }}
                    className={cn(
                      "py-1.5 text-xs rounded transition-colors",
                      isMonthDisabled(m) ? "text-gray-300 cursor-not-allowed" :
                      selYear === year && String(m) === month ? "text-white" : "text-gray-600 hover:bg-gray-100"
                    )}
                    style={selYear === year && String(m) === month && !isMonthDisabled(m) ? { backgroundColor: PRIMARY } : {}}
                  >
                    {m}月
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// 城市三级选择器 - 模拟智联 s-cascader 省→市→区
export function CityCascader({ province, city, district, onChange, level = 3 }: {
  province: string
  city: string
  district?: string
  onChange: (prov: string, cityName: string, cityCode: string, distName?: string, distCode?: string) => void
  level?: 2 | 3  // 2=省市二级(户口), 3=省市区三级(现居住)
}) {
  const [open, setOpen] = useState(false)
  const [selProv, setSelProv] = useState<ZhilianProvinceFull | null>(null)
  const [selCity, setSelCity] = useState<ZhilianCityWithDistricts | null>(null)

  // 过滤掉"热门"和"国外"
  const provinces = ZHILIAN_CITIES_FULL.filter(p => p.name !== "热门" && p.name !== "国外")

  const displayText = [province, city, level === 3 ? district : ""].filter(Boolean).join("-")

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen(!open)
          const foundProv = provinces.find(p => p.name === province)
          setSelProv(foundProv || null)
          const foundCity = foundProv?.cities.find(c => c.name === city)
          setSelCity(foundCity || null)
        }}
        className={cn(
          "w-full h-9 px-3 text-sm border rounded-md bg-white text-left flex items-center justify-between",
          open ? "border-[#2A7BFF]" : "border-gray-300"
        )}
      >
        <span className={displayText ? "text-gray-900" : "text-gray-400"}>{displayText || "请选择"}</span>
        <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
      </button>
      {open && (
        <div className="absolute z-50 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg flex" style={{ width: level === 3 ? 480 : 340 }}>
          {/* 省列 */}
          <div className="w-[130px] border-r border-gray-100 max-h-[280px] overflow-y-auto py-1">
            {provinces.map(p => (
              <button
                key={p.code}
                type="button"
                onClick={() => { setSelProv(p); setSelCity(null) }}
                className={cn(
                  "w-full px-3 py-1.5 text-xs text-left transition-colors",
                  selProv?.code === p.code ? "text-white" : "text-gray-700 hover:bg-gray-50"
                )}
                style={selProv?.code === p.code ? { backgroundColor: PRIMARY } : {}}
              >
                {p.name}
              </button>
            ))}
          </div>
          {/* 市列 */}
          {selProv && (
            <div className="w-[130px] border-r border-gray-100 max-h-[280px] overflow-y-auto py-1">
              {selProv.cities.map(c => (
                <button
                  key={c.code}
                  type="button"
                  onClick={() => {
                    if (level === 2) {
                      onChange(selProv.name, c.name, c.code)
                      setOpen(false)
                    } else {
                      setSelCity(c)
                    }
                  }}
                  className={cn(
                    "w-full px-3 py-1.5 text-xs text-left transition-colors",
                    selCity?.code === c.code ? "text-white" : "text-gray-700 hover:bg-gray-50"
                  )}
                  style={selCity?.code === c.code ? { backgroundColor: PRIMARY } : {}}
                >
                  {c.name}
                </button>
              ))}
            </div>
          )}
          {/* 区列 (仅level=3) */}
          {level === 3 && selCity && selCity.districts.length > 0 && (
            <div className="w-[200px] max-h-[280px] overflow-y-auto py-1 px-2">
              <div className="flex flex-wrap gap-1">
                {/* 全XX 选项 - 表示不限区 */}
                <button
                  type="button"
                  onClick={() => {
                    onChange(selProv!.name, selCity.name, selCity.code, selCity.name, selCity.code)
                    setOpen(false)
                  }}
                  className={cn(
                    "px-2 py-1 text-xs rounded border transition-colors",
                    district === selCity.name
                      ? "border-[#2A7BFF] text-[#2A7BFF]"
                      : "border-gray-200 text-gray-600 hover:border-gray-300"
                  )}
                >
                  全{selCity.name}
                </button>
                {selCity.districts.map(d => (
                  <button
                    key={d.code}
                    type="button"
                    onClick={() => {
                      onChange(selProv!.name, selCity.name, selCity.code, d.name, d.code)
                      setOpen(false)
                    }}
                    className={cn(
                      "px-2 py-1 text-xs rounded border transition-colors",
                      district === d.name
                        ? "border-[#2A7BFF] text-[#2A7BFF]"
                        : "border-gray-200 text-gray-600 hover:border-gray-300"
                    )}
                  >
                    {d.name}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// 简单城市下拉（求职意向等模块用）
export function CitySelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select
      className="w-full h-9 px-3 text-sm border border-gray-300 rounded-md bg-white focus:outline-none"
      value={value}
      onChange={e => onChange(e.target.value)}
    >
      <option value="">请选择城市</option>
      {ZHILIAN_PROVINCES.map(prov => (
        <optgroup key={prov.code} label={prov.name}>
          {prov.cities.map(city => (
            <option key={city.code} value={city.code}>{city.name}</option>
          ))}
        </optgroup>
      ))}
    </select>
  )
}

// 简单年月输入（工作/教育/项目/培训/证书等模块用）
export function YearMonthInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <input
      type="month"
      className="w-full h-9 px-3 text-sm border border-gray-300 rounded-md focus:outline-none"
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
    />
  )
}
