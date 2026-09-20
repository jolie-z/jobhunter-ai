"use client"

import { useEffect, useState } from "react"

interface CatalogueItem {
  key: string       // 对应 sectionId 映射
  label: string     // 显示文字
  sectionId: string // 用于 scrollIntoView 的 DOM id
}

// 猎聘官网侧边栏导航项（10 大模块标准顺序）
const CATALOGUE_ITEMS: CatalogueItem[] = [
  { key: "baseInfo",       label: "基本信息",  sectionId: "section-baseInfo" },
  { key: "selfEval",       label: "优势亮点",  sectionId: "section-selfEval" },
  { key: "expectations",   label: "求职期望",  sectionId: "section-expectations" },
  { key: "workExp",        label: "工作经历",  sectionId: "section-workExp" },
  { key: "projects",       label: "项目经历",  sectionId: "section-projects" },
  { key: "education",      label: "教育经历",  sectionId: "section-education" },
  { key: "certificates",   label: "资格证书",  sectionId: "section-certificates" },
  { key: "skillTags",      label: "技能标签",  sectionId: "section-skillTags" },
  { key: "languages",      label: "语言能力",  sectionId: "section-languages" },
  { key: "additionalInfo", label: "附加信息",  sectionId: "section-additionalInfo" },
]

const LIEPIN_PRIMARY = "#FF6B00"

interface LiepinCatalogueProps {
  /** 哪些 section key 有数据（没数据的隐藏；不传默认展示全部） */
  visibleKeys?: string[]
}

export function LiepinCatalogue({ visibleKeys }: LiepinCatalogueProps) {
  const [activeKey, setActiveKey] = useState<string>("baseInfo")

  // 监听滚动，高亮当前可见的 section
  useEffect(() => {
    const elements = CATALOGUE_ITEMS
      .map((item) => document.getElementById(item.sectionId))
      .filter(Boolean) as HTMLElement[]

    if (elements.length === 0) return

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
      <div className="bg-white border border-[#e8e8e8] rounded-xl shadow-sm overflow-hidden">
        {/* 简历目录 标题 */}
        <h2
          className="m-0 text-sm font-semibold text-[#222] leading-5 border-b border-gray-100"
          style={{ padding: "12px 16px" }}
        >
          简历目录
        </h2>

        {/* 导航列表 */}
        <ul className="list-none m-0 p-1 space-y-0.5">
          {items.map((item) => {
            const isActive = activeKey === item.key
            return (
              <li
                key={item.key}
                className="relative flex items-center cursor-pointer rounded-lg transition-colors duration-200 hover:bg-orange-50/50 select-none"
                style={{
                  padding: "8px 14px",
                  height: 36,
                  boxSizing: "border-box",
                  fontSize: 13,
                  lineHeight: "20px",
                  color: isActive ? LIEPIN_PRIMARY : "#444",
                  fontWeight: isActive ? 600 : 400,
                  background: isActive ? "rgba(255, 107, 0, 0.08)" : "transparent",
                }}
                onClick={() => handleClick(item)}
              >
                {/* 激活态左侧猎聘橙竖条 */}
                {isActive && (
                  <span
                    className="absolute rounded-sm"
                    style={{
                      left: 3,
                      top: "50%",
                      transform: "translateY(-50%)",
                      width: 3,
                      height: 16,
                      background: LIEPIN_PRIMARY,
                    }}
                  />
                )}
                <span>{item.label}</span>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
