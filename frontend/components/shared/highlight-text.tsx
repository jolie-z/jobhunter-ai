import React from "react"
import { LinkifyText } from "./linkify-text"

// 🌟 HighlightText 组件：使用正则切割实现字级别高亮
export function HighlightText({
  text,
  searchKeyword,
  currentMatchIndex,
  onRegisterMatch
}: {
  text: string
  searchKeyword: string
  currentMatchIndex: number
  onRegisterMatch: (id: string) => number
}) {
  if (!searchKeyword.trim()) {
    // 🌟 即使没有搜索关键词，也应用 URL 超链接转换
    return <LinkifyText text={text} />
  }

  const regex = new RegExp(`(${searchKeyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
  const parts = text.split(regex)

  return (
    <>
      {parts.map((part, index) => {
        if (part.toLowerCase() === searchKeyword.toLowerCase()) {
          // 匹配的关键词，注册并获取全局索引
          const matchId = `search-match-${index}-${part}`
          const globalIndex = onRegisterMatch(matchId)
          const isActive = globalIndex === currentMatchIndex

          return (
            <mark
              key={`${index}-${part}`}
              id={matchId}
              className={isActive
                ? 'bg-orange-500 text-white font-bold px-0.5 rounded'
                : 'bg-yellow-200 text-black px-0.5 rounded'
              }
            >
              {part}
            </mark>
          )
        }
        // 普通文本也应用 URL 超链接转换
        return <LinkifyText key={index} text={part} />
      })}
    </>
  )
}
