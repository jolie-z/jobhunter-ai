"use client"

import React, { useState } from "react"
import { Plus, Trash2, Tag, ChevronDown, ChevronRight, Layers, Sparkles } from "lucide-react"

export interface DynamicFieldSlotProps {
  /** 当前条目/对象数据 */
  data: Record<string, any>
  /** 已由固定表单组件渲染的已知键列表（支持可选） */
  excludeKeys?: string[]
  /** 已知基准表单模版对象（可选，自动提取 Object.keys 动态反射过滤） */
  template?: Record<string, any>
  /** 字段变动回调 (key, value) */
  onChange: (key: string, value: any) => void
  /** 是否只读 */
  readOnly?: boolean
  /** 标题提示 */
  title?: string
}

/**
 * 启发式动态识别系统底层元数据/内部运行时影子属性（拒绝枚举死列表）
 * 依据命名模式、时间戳格式、长串流水ID、图床URL与影子冗余进行自动特征分类
 */
export function isSystemMetadata(key: string, value: any, allData?: Record<string, any>): boolean {
  if (!key || typeof key !== "string") return true
  const k = key.trim()

  // 1. 私有属性与底层派生翻译/格式化字符串
  if (k.startsWith("_") || k.startsWith("$") || k.endsWith("Translation") || k.endsWith("String") || k.endsWith("Format")) {
    return true
  }

  // 2. 通用底层主键、序号与流水路径
  if (["id", "path", "key", "_deprecated_fields", "subType", "index", "sort", "order", "dailyWage", "durationInMonths", "workdays", "workYear", "salaryConfidentiality", "salaryTimes"].includes(k)) {
    return true
  }

  // 3. 启发式时间戳特征识别：字段带 Time/Date 且值为秒级完整时间戳 (如 2020-09-12 00:21:51 或 1970/01/01 08:00:00)
  if (/(Time|_time|Date|_date|modify|create|verify)/i.test(k)) {
    if (typeof value === "string" && /^\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}/.test(value.trim())) {
      return true
    }
  }

  // 4. 启发式系统主键/流水号特征识别：字段带 Id/Code/Token/Key/Serial 且值为纯数字长串或工商统一信用代码/哈希
  if (/(Id|_id|ID|moduleId|licenseId|securityId|encryptId|sortId|orderId|token|uuid|Serial|kgId)/i.test(k)) {
    if (typeof value === "string") {
      const v = value.trim()
      // 纯数字ID (如 369525152, 0006) 或 18位工商执照号 (如 91440101MA5D64Q828) 或 16+位哈希
      if (/^\d{4,}$/.test(v) || /^[0-9A-Z]{15,20}$/.test(v) || /^[a-f0-9-]{32,}$/i.test(v) || v === "") {
        return true
      }
    } else if (typeof value === "number") {
      return true
    }
  }

  // 5. 启发式 CDN 静态资源图床特征识别：字段带 Url/Logo/Avatar 且值为平台图床链接
  if (/(logo|avatar|icon|thumb|image|img|Url|_url)$/i.test(k)) {
    if (typeof value === "string" && /^https?:\/\/.*(cdn|homelogo|avatar|default|\.png|\.jpg|\.jpeg|\.svg)/i.test(value)) {
      return true
    }
  }

  // 6. 启发式平台系统标志位与服务端标签识别 (包含 51job/BOSS/智联/猎聘的服务端标签)
  if (/^(complete|isComplete|isEnglish|isOverseas|seekType|isLock|anonymous|showRealName|disAgreePrivacy|personalization|isVerify|isMobileVerify|toToday|toNow|isNow|is211|is985|isMba|isFullTime|is_211|is_985|is_mba|is_full_time|label|labels|tag|tags|logoUrl|avatarUrl|isHiddenForB|workIsReferences|proExpIsCurrent|academicCertificateNumber|academicCertificateVerifyState|eduCampusFullTime|eduDegree|eduMajorSmallType|eduMajorT|newEduMajorT|eduMinorName|eduOverseaseExperienceYear|eduRank|eduResearchArea|eduSchoolCode|eduSpecializedCourses|schoolLogo|schoolTag|majorKgId|schoolNameKgId)$/i.test(k)) {
    return true
  }

  // 7. 问答与背调专属字段过滤
  if (/(Question|Answer|workRef)/i.test(k)) {
    return true
  }

  // 8. 动态影子镜像冗余字段特征识别 (Shadow Mirror Recognition)
  if (/(VocationalSkills|skillTag|skill_tag)/i.test(k)) {
    return true
  }

  // 如果当前字段的值，与已知主字段（如 skills 数组，或某个 code 字段）的内容完全一致或互为子集镜像
  if (allData && typeof allData === "object") {
    // 智联培训机构 trainAgency 与 trainName 冗余
    if (k === "trainAgency" && allData.trainName !== undefined) {
      return true
    }
    // 智联职位 title 与 jobTitle 冗余
    if (k === "title" && (allData.jobTitle !== undefined || allData.proExpProjectName !== undefined)) {
      return true
    }
    // 智联新行业/职位前缀镜像 (newIndustry vs wnewIndustry / pnewIndustry)
    if (k.startsWith("new") && (allData["w" + k] !== undefined || allData["p" + k] !== undefined || allData["edu" + k] !== undefined)) {
      return true
    }
    // 智联大类职位编码 wnewJobType 在已选小类 wnewJobSubType 时自动归属
    if (k === "wnewJobType" && allData.wnewJobSubType !== undefined) {
      return true
    }
    // 智联老版分类编码被新版取代 (industry, jobType, jobSubType)
    if (["industry", "jobType", "jobSubType"].includes(k) && (allData.wnewIndustry !== undefined || allData.wnewJobSubType !== undefined || allData.pnewPreferredIndustry !== undefined)) {
      return true
    }
    // 比如 职业技能对象/字符串列表 与 skills 数组内容重合
    if (Array.isArray(value) && Array.isArray(allData.skills)) {
      const isSkillMirror = value.every(item => {
        if (typeof item === "string") return allData.skills.includes(item)
        if (item && typeof item === "object" && item.skill) return allData.skills.includes(item.skill)
        return false
      })
      if (isSkillMirror) return true
    }
    // 比如 平台标签数组为空
    if (k.endsWith("Labels") && Array.isArray(value) && value.length === 0) {
      return true
    }
    // 比如 workIndustryNew 与 workIndustry 或 industry 相同
    if (k.endsWith("New") && (allData[k.replace(/New$/, "")] !== undefined || allData.industry !== undefined)) {
      return true
    }
  }

  return false
}

export function DynamicFieldSlot({
  data,
  excludeKeys = [],
  template,
  onChange,
  readOnly = false,
  title = "动态扩展属性 (官网新字段)",
}: DynamicFieldSlotProps) {
  const [newTagInput, setNewTagInput] = useState<Record<string, string>>({})
  const [expandedSubList, setExpandedSubList] = useState<Record<string, boolean>>({})

  if (!data || typeof data !== "object") return null

  // 1. 从基准模版中动态反射提取已知字段集合
  const templateKeys = template && typeof template === "object" ? Object.keys(template) : []
  const knownKeySet = new Set([...excludeKeys, ...templateKeys])

  // 2. 动态过滤出真正的新增业务扩展字段（排除已知表单字段与启发式识别的系统元数据）
  const dynamicKeys = Object.keys(data).filter(
    k => !knownKeySet.has(k) && !isSystemMetadata(k, data[k], data)
  )

  if (dynamicKeys.length === 0) return null

  const handleScalarChange = (key: string, val: string | boolean | number) => {
    onChange(key, val)
  }

  const handleAddTag = (key: string) => {
    const text = (newTagInput[key] || "").trim()
    if (!text) return
    const currentList = Array.isArray(data[key]) ? [...data[key]] : []
    if (!currentList.includes(text)) {
      currentList.push(text)
      onChange(key, currentList)
    }
    setNewTagInput(prev => ({ ...prev, [key]: "" }))
  }

  const handleRemoveTag = (key: string, idx: number) => {
    const currentList = Array.isArray(data[key]) ? [...data[key]] : []
    currentList.splice(idx, 1)
    onChange(key, currentList)
  }

  const handleAddSubItem = (key: string, sampleItem: Record<string, any> = {}) => {
    const currentList = Array.isArray(data[key]) ? [...data[key]] : []
    const newItem: Record<string, any> = {}
    // 拷贝已有条目的键结构，值置空
    Object.keys(sampleItem).forEach(k => {
      newItem[k] = ""
    })
    if (Object.keys(newItem).length === 0) {
      newItem["name"] = ""
      newItem["desc"] = ""
    }
    currentList.push(newItem)
    onChange(key, currentList)
  }

  const handleRemoveSubItem = (key: string, idx: number) => {
    const currentList = Array.isArray(data[key]) ? [...data[key]] : []
    currentList.splice(idx, 1)
    onChange(key, currentList)
  }

  const handleSubItemFieldChange = (key: string, idx: number, subKey: string, val: any) => {
    const currentList = Array.isArray(data[key]) ? [...data[key]] : []
    if (currentList[idx]) {
      currentList[idx] = { ...currentList[idx], [subKey]: val }
      onChange(key, currentList)
    }
  }

  return (
    <div className="mt-4 pt-3 border-t border-dashed border-indigo-100/80 bg-indigo-50/30 rounded-xl p-3.5 space-y-3">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-indigo-700">
        <Sparkles className="w-3.5 h-3.5 text-indigo-500" />
        <span>{title}</span>
        <span className="text-[10px] text-indigo-400 font-normal">
          ({dynamicKeys.length} 个自适应字段)
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {dynamicKeys.map(key => {
          const val = data[key]

          // 1. 数组形态分流
          if (Array.isArray(val)) {
            // A) 对象子列表形态
            if (val.length > 0 && typeof val[0] === "object" && val[0] !== null) {
              const isExpanded = expandedSubList[key] ?? true
              const sampleObj = val[0] || {}
              const subFields = Object.keys(sampleObj).filter(sk => !sk.startsWith("_"))

              return (
                <div
                  key={key}
                  className="col-span-full bg-white/80 border border-indigo-100 rounded-lg p-2.5 shadow-sm space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <button
                      type="button"
                      onClick={() => setExpandedSubList(prev => ({ ...prev, [key]: !isExpanded }))}
                      className="flex items-center gap-1.5 text-xs font-medium text-gray-700 hover:text-indigo-600 transition-colors"
                    >
                      {isExpanded ? (
                        <ChevronDown className="w-3.5 h-3.5 text-indigo-500" />
                      ) : (
                        <ChevronRight className="w-3.5 h-3.5 text-indigo-500" />
                      )}
                      <Layers className="w-3.5 h-3.5 text-indigo-500" />
                      <span>{key}</span>
                      <span className="text-[10px] bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded-full">
                        子列表 ({val.length} 项)
                      </span>
                    </button>

                    {!readOnly && (
                      <button
                        type="button"
                        onClick={() => handleAddSubItem(key, sampleObj)}
                        className="inline-flex items-center gap-1 px-2 py-1 text-[11px] font-medium text-indigo-600 bg-indigo-50 hover:bg-indigo-100 rounded border border-indigo-200 transition-colors"
                      >
                        <Plus className="w-3 h-3" />
                        添加一项
                      </button>
                    )}
                  </div>

                  {isExpanded && (
                    <div className="space-y-2 pt-1">
                      {val.map((item, itemIdx) => (
                        <div
                          key={itemIdx}
                          className="bg-gray-50/80 border border-gray-200/80 rounded-md p-2 relative group"
                        >
                          <div className="flex items-center justify-between mb-1.5">
                            <span className="text-[10px] font-semibold text-gray-500">
                              #{itemIdx + 1}
                            </span>
                            {!readOnly && (
                              <button
                                type="button"
                                onClick={() => handleRemoveSubItem(key, itemIdx)}
                                className="text-gray-400 hover:text-red-500 transition-colors p-0.5"
                                title="删除此项"
                              >
                                <Trash2 className="w-3 h-3" />
                              </button>
                            )}
                          </div>

                          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
                            {subFields.map(subKey => (
                              <div key={subKey} className="space-y-0.5">
                                <label className="text-[10px] text-gray-500 block truncate">
                                  {subKey}
                                </label>
                                <input
                                  type="text"
                                  disabled={readOnly}
                                  value={item[subKey] ?? ""}
                                  onChange={e =>
                                    handleSubItemFieldChange(key, itemIdx, subKey, e.target.value)
                                  }
                                  className="w-full text-xs px-2 py-1 bg-white border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-indigo-500"
                                />
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            }

            // B) 纯字符串标签胶囊数组形态 (Tag Chips)
            return (
              <div
                key={key}
                className="col-span-full bg-white/80 border border-indigo-100 rounded-lg p-2.5 shadow-sm space-y-1.5"
              >
                <div className="flex items-center gap-1.5 text-xs font-medium text-gray-700">
                  <Tag className="w-3.5 h-3.5 text-indigo-500" />
                  <span>{key}</span>
                  <span className="text-[10px] text-gray-400 font-normal">
                    (标签数组 · {val.length} 个)
                  </span>
                </div>

                <div className="flex flex-wrap gap-1.5 items-center pt-1">
                  {val.map((tagItem: string, tagIdx: number) => (
                    <span
                      key={tagIdx}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-indigo-50 text-indigo-700 border border-indigo-200/80"
                    >
                      {String(tagItem)}
                      {!readOnly && (
                        <button
                          type="button"
                          onClick={() => handleRemoveTag(key, tagIdx)}
                          className="hover:text-red-500 transition-colors ml-0.5"
                        >
                          ×
                        </button>
                      )}
                    </span>
                  ))}

                  {!readOnly && (
                    <div className="inline-flex items-center gap-1">
                      <input
                        type="text"
                        placeholder="输入新标签后回车"
                        value={newTagInput[key] || ""}
                        onChange={e =>
                          setNewTagInput(prev => ({ ...prev, [key]: e.target.value }))
                        }
                        onKeyDown={e => {
                          if (e.key === "Enter") {
                            e.preventDefault()
                            handleAddTag(key)
                          }
                        }}
                        className="text-xs px-2 py-0.5 w-28 border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-indigo-500"
                      />
                      <button
                        type="button"
                        onClick={() => handleAddTag(key)}
                        className="p-0.5 text-indigo-600 hover:bg-indigo-50 rounded"
                      >
                        <Plus className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )
          }

          // 2. 布尔开关形态
          if (typeof val === "boolean") {
            return (
              <div
                key={key}
                className="flex items-center justify-between bg-white/80 border border-indigo-100 rounded-lg px-3 py-2"
              >
                <label className="text-xs font-medium text-gray-700 truncate">{key}</label>
                <input
                  type="checkbox"
                  disabled={readOnly}
                  checked={val}
                  onChange={e => handleScalarChange(key, e.target.checked)}
                  className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 h-4 w-4"
                />
              </div>
            )
          }

          // 3. 普通标量文本输入框形态
          return (
            <div
              key={key}
              className="bg-white/80 border border-indigo-100 rounded-lg px-3 py-2 space-y-1"
            >
              <label className="text-xs font-medium text-gray-700 block truncate">{key}</label>
              <input
                type="text"
                disabled={readOnly}
                value={val ?? ""}
                onChange={e => handleScalarChange(key, e.target.value)}
                className="w-full text-xs px-2 py-1 bg-white border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          )
        })}
      </div>
    </div>
  )
}
