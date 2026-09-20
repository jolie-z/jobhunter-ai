import React, { type ReactNode } from "react"

// 🌟 行内 Markdown 渲染：解析 **bold** 片段
export function renderInlineMarkdown(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*\n]+\*\*)/g)
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return (
        <strong key={i} className="font-semibold text-foreground">
          {part.slice(2, -2)}
        </strong>
      )
    }
    return <span key={i}>{part}</span>
  })
}

// 🌟 Markdown 简历预览组件：支持加粗、• 列表、多层缩进，对标 Copilot 排版
export function MdPreview({ text }: { text: string }) {
  if (!text.trim()) {
    return (
      <span className="text-muted-foreground/50 italic text-[10px] select-none">
        点击编辑内容…
      </span>
    )
  }

  const lines = text.split("\n")
  const nodes: ReactNode[] = []
  let listBuffer: { content: string; indent: number }[] = []

  const flushList = (key: string) => {
    if (listBuffer.length === 0) return
    const firstIndent = listBuffer[0].indent
    nodes.push(
      <ul key={key} className={`space-y-0.5 my-0.5 ${firstIndent >= 4 ? "pl-6" : "pl-3"}`}>
        {listBuffer.map((item, i) => (
          <li key={i} className="flex gap-1.5 leading-relaxed">
            <span className="shrink-0 text-muted-foreground select-none">•</span>
            <span className="flex-1">{renderInlineMarkdown(item.content)}</span>
          </li>
        ))}
      </ul>
    )
    listBuffer = []
  }

  lines.forEach((rawLine, idx) => {
    const trimmed = rawLine.trimStart()
    const indent = rawLine.length - trimmed.length
    const bulletMatch = trimmed.match(/^[•\-]\s+(.*)$/)

    if (bulletMatch) {
      listBuffer.push({ content: bulletMatch[1], indent })
      return
    }

    flushList(`list-${idx}`)

    if (trimmed === "") {
      if (nodes.length > 0) nodes.push(<div key={`gap-${idx}`} className="h-1" />)
      return
    }

    if (trimmed.startsWith("## ")) {
      nodes.push(
        <p key={`h2-${idx}`} className="font-semibold text-[11px] leading-relaxed mt-1.5">
          {renderInlineMarkdown(trimmed.slice(3))}
        </p>
      )
      return
    }

    const paddingClass = indent >= 4 ? "pl-5" : indent >= 2 ? "pl-3" : ""
    nodes.push(
      <p key={`p-${idx}`} className={`text-[11px] leading-relaxed ${paddingClass}`}>
        {renderInlineMarkdown(rawLine)}
      </p>
    )
  })

  flushList("list-final")
  return <div className="text-[11px] text-foreground">{nodes}</div>
}
