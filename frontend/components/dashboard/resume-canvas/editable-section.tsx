"use client"

import { useEffect, useRef, useState } from "react"
import { Sparkles, Pencil } from "lucide-react"
import { Textarea } from "@/components/ui/textarea"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import ReactMarkdown from 'react-markdown'

import { stripConfidenceTags } from "@/lib/utils/text-formatters"

// ─── 证据强度标签清理（用户要求彻底去除 [稳] [需补证] 尾缀） ───
function processConfidenceTags(md: string): string {
  return stripConfidenceTags(md)
}

function ConfidenceStrong({ children, ...props }: any) {
  return <strong {...props}>{children}</strong>
}

interface EditableSectionProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  className?: string
  onPolish?: (selectedText: string) => void

  // 接收上层传来的高亮属性
  moduleId?: string
  blockId?: string
  field?: string
  findText?: string
  matches?: any[]
  currentMatchIndex?: number
}

// 独立的组件用于渲染纯文本中的高亮部分
function HighlightedText({ text, moduleId, blockId, field, findText, matches, currentMatchIndex }: any) {
  const currentMatchRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (currentMatchRef.current) {
      currentMatchRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [currentMatchIndex]);

  if (!findText) return <>{text}</>;

  const parts = text.split(new RegExp(`(${findText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'));
  let localMatchCounter = 0;
  const blockMatchesStartIdx = matches?.findIndex((m: any) => m.moduleId === moduleId && m.blockId === blockId && m.field === field) ?? -1;

  return (
    <>
      {parts.map((part: string, index: number) => {
        if (part.toLowerCase() === findText.toLowerCase() && blockMatchesStartIdx !== -1) {
          const globalMatchIndex = blockMatchesStartIdx + localMatchCounter;
          localMatchCounter++;
          const isCurrent = globalMatchIndex === currentMatchIndex;

          return (
            <mark
              key={index}
              ref={isCurrent ? currentMatchRef : null}
              className={cn(
                "rounded-sm px-0.5 font-medium transition-colors",
                isCurrent ? "bg-amber-400 text-amber-950 shadow-sm" : "bg-amber-200/60 text-slate-800"
              )}
            >
              {part}
            </mark>
          )
        }
        return <span key={index}>{part}</span>
      })}
    </>
  )
}

export function EditableSection({
  value,
  onChange,
  placeholder,
  className,
  onPolish,
  moduleId,
  blockId,
  field,
  findText,
  matches,
  currentMatchIndex,
}: EditableSectionProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const [selection, setSelection] = useState("")
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    setDraft(value)
  }, [value])

  useEffect(() => {
    if (editing && textareaRef.current) {
      const el = textareaRef.current
      el.focus()
      el.setSelectionRange(el.value.length, el.value.length)
      autoSize(el)
    }
  }, [editing])

  function autoSize(el: HTMLTextAreaElement) {
    el.style.height = "auto"
    el.style.height = `${el.scrollHeight}px`
  }

  function commit() {
    onChange(draft)
    setEditing(false)
    setSelection("")
  }

  if (!editing) {
    return (
      <div
        role="button"
        tabIndex={0}
        onClick={() => setEditing(true)}
        className={cn(
          "group relative cursor-text whitespace-pre-wrap rounded-md px-3 py-2 text-sm leading-relaxed text-slate-800 transition-colors hover:bg-slate-50",
          className,
        )}
      >
        {value ? (
          findText ? (
            <HighlightedText
              text={value}
              moduleId={moduleId} blockId={blockId} field={field}
              findText={findText} matches={matches} currentMatchIndex={currentMatchIndex}
            />
          ) : (
            <div className="prose prose-sm prose-slate max-w-none prose-p:my-1 prose-ul:my-1 prose-li:my-0.5">
              <ReactMarkdown components={{ strong: ConfidenceStrong }}>{processConfidenceTags(value)}</ReactMarkdown>
            </div>
          )
        ) : (
          <span className="text-slate-400">{placeholder ?? "点击编辑…"}</span>
        )}
        <span className="absolute right-2 top-2 hidden items-center gap-1 rounded bg-slate-900/80 px-1.5 py-0.5 text-[10px] font-medium text-white group-hover:flex">
          <Pencil className="size-3" /> 编辑
        </span>
      </div>
    )
  }

  return (
    <div className="relative">
      <Textarea
        ref={textareaRef}
        value={draft}
        onChange={(e) => { setDraft(e.target.value); autoSize(e.target) }}
        onBlur={commit}
        placeholder={placeholder}
        className={cn("min-h-[80px] resize-none text-sm leading-relaxed", className)}
      />
      <div className="mt-2 flex justify-end gap-2">
        <Button size="sm" variant="ghost" className="h-7" onMouseDown={(e) => { e.preventDefault(); setDraft(value); setEditing(false) }}>取消</Button>
        <Button size="sm" className="h-7" onMouseDown={(e) => e.preventDefault()} onClick={commit}>完成</Button>
      </div>
    </div>
  )
}