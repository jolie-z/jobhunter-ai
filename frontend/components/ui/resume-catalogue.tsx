"use client"

import { useEffect, useState } from "react"
import { Plus } from "lucide-react"

interface CatalogueItem {
  key: string       // 对应 sectionId 映射
  label: string     // 显示文字
  sectionId: string // 用于 scrollIntoView 的 DOM id
}

// BOSS官网侧边栏导航项（顺序照抄官网）
const CATALOGUE_ITEMS: CatalogueItem[] = [
  { key: "baseInfo",         label: "个人信息",  sectionId: "section-baseInfo" },
  { key: "userDesc",         label: "个人优势",  sectionId: "section-selfEval" },
  { key: "expectList",       label: "期望职位",  sectionId: "section-expectList" },
  { key: "workExpList",      label: "工作经历",  sectionId: "section-workExp" },
  { key: "projectExpList",   label: "项目经历",  sectionId: "section-projectExpList" },
  { key: "educationExpList", label: "教育经历",  sectionId: "section-educationExpList" },
  { key: "certificationList",label: "资格证书",  sectionId: "section-certificationList" },
  { key: "stayAbroad",       label: "驻外选项",  sectionId: "section-stayAbroad" },
]

interface ResumeCatalogueProps {
  /** 哪些 section key 有数据（没数据的隐藏） */
  visibleKeys?: string[]
}

export function ResumeCatalogue({ visibleKeys }: ResumeCatalogueProps) {
  const [activeKey, setActiveKey] = useState<string>("baseInfo")

  // 监听滚动，高亮当前可见的 section
  useEffect(() => {
    const elements = CATALOGUE_ITEMS
      .map((item) => document.getElementById(item.sectionId))
      .filter(Boolean) as HTMLElement[]

    if (elements.length === 0) return
    if (typeof IntersectionObserver === "undefined") return // jsdom/SSR 环境无此 API

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)

        if (visible.length > 0) {
          const id = visible[0].target.id
          const item = CATALOGUE_ITEMS.find((c) => c.sectionId === id)
          if (item) setActiveKey(item.key)
        }
      },
      { rootMargin: "-220px 0px -40% 0px", threshold: 0 }
    )

    elements.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [])

  const handleClick = (item: CatalogueItem) => {
    const el = document.getElementById(item.sectionId)
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" })
      setActiveKey(item.key)
    }
  }

  // 过滤出有数据的项
  const items = visibleKeys
    ? CATALOGUE_ITEMS.filter((item) => visibleKeys.includes(item.key))
    : CATALOGUE_ITEMS

  return (
    <div className="shrink-0" style={{ width: 128 }}>
      <div className="bg-white rounded-tl-2xl rounded-tr-2xl">
        {/* 简历目录 标题 */}
        <h2
          className="m-0 text-sm font-semibold text-[#222] leading-5"
          style={{ padding: "12px 20px" }}
        >
          简历目录
        </h2>

        {/* 导航列表 */}
        <ul className="list-none m-0 p-1">
          {items.map((item) => {
            const isActive = activeKey === item.key
            return (
              <li
                key={item.key}
                className="relative flex items-center cursor-pointer rounded transition-colors duration-200 hover:bg-gray-100"
                style={{
                  padding: "10px 16px",
                  height: 40,
                  boxSizing: "border-box",
                  fontSize: 14,
                  lineHeight: "20px",
                  color: isActive ? "#00beab" : "#333",
                  fontWeight: isActive ? 500 : 400,
                  background: isActive ? "rgba(0, 190, 171, 0.06)" : "transparent",
                }}
                onClick={() => handleClick(item)}
              >
                {/* 激活态左侧竖条 */}
                {isActive && (
                  <span
                    className="absolute rounded-sm"
                    style={{
                      left: 4,
                      top: "50%",
                      transform: "translateY(-50%)",
                      width: 3,
                      height: 16,
                      background: "#00beab",
                    }}
                  />
                )}
                <span>{item.label}</span>
              </li>
            )
          })}

          {/* 志愿者经历 - BOSS官网额外项（暂未开发） */}
          <li
            className="relative flex items-center rounded group"
            style={{
              padding: "10px 16px",
              height: 40,
              boxSizing: "border-box",
              fontSize: 14,
              lineHeight: "20px",
              color: "#999",
            }}
          >
            <span className="truncate">{/* 志愿者经历 */}志愿者经历</span>
            <Plus className="w-4 h-4 ml-auto opacity-50" />
            {/* hover tooltip */}
            <div className="hidden group-hover:block absolute left-full ml-2 top-1/2 -translate-y-1/2 bg-[#333] text-white text-xs px-2.5 py-1.5 rounded whitespace-nowrap z-10">
              展示你的志愿者精神
            </div>
          </li>
        </ul>
      </div>
    </div>
  )
}
