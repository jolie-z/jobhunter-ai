import React from "react"

// 🌟 LinkifyText 组件：自动将文本中的 URL 转换为可点击的超链接
export function LinkifyText({ text }: { text: string }) {
  // URL 正则表达式：匹配 http:// 或 https:// 开头的链接
  const urlRegex = /(https?:\/\/[^\s]+)/g
  const parts = text.split(urlRegex)

  return (
    <>
      {parts.map((part, index) => {
        // 如果是 URL，渲染为超链接
        if (part.match(urlRegex)) {
          return (
            <a
              key={index}
              href={part}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              {part}
            </a>
          )
        }
        // 普通文本直接返回
        return <span key={index}>{part}</span>
      })}
    </>
  )
}
