"use client"

import React, { useState, useRef, useEffect } from "react"
import ReactMarkdown from "react-markdown"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

interface MarkdownEditorProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  className?: string
  minHeight?: string
}

export function MarkdownEditor({ value, onChange, placeholder, className, minHeight = "min-h-[120px]" }: MarkdownEditorProps) {
  const [isEditing, setIsEditing] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Auto-focus when switching to edit mode
  useEffect(() => {
    if (isEditing && textareaRef.current) {
      textareaRef.current.focus()
      // Optional: Move cursor to the end
      const len = textareaRef.current.value.length
      textareaRef.current.setSelectionRange(len, len)
    }
  }, [isEditing])

  if (isEditing) {
    return (
      <Textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={() => setIsEditing(false)}
        placeholder={placeholder}
        className={cn(minHeight, "resize-y bg-secondary/30 text-[13px] leading-relaxed font-mono", className)}
      />
    )
  }

  return (
    <div
      onClick={() => setIsEditing(true)}
      className={cn(
        minHeight,
        "cursor-text rounded-md border border-transparent hover:border-border/50 hover:bg-secondary/10 p-3 text-[13px] leading-relaxed transition-colors",
        className
      )}
    >
      {value ? (
        <div className="prose prose-sm dark:prose-invert max-w-none prose-p:my-1 prose-ul:my-1 prose-li:my-0.5">
          <ReactMarkdown>{value}</ReactMarkdown>
        </div>
      ) : (
        <span className="text-muted-foreground">{placeholder || "点击此处添加描述..."}</span>
      )}
    </div>
  )
}
