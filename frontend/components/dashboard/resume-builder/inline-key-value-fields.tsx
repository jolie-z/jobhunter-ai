"use client"

import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Plus, X } from "lucide-react"

export interface KVField {
  id: number
  key: string
  value: string
  valuePlaceholder?: string
}

let kvSeed = 5000
export const nextKvId = () => ++kvSeed

interface InlineKeyValueFieldsProps {
  fields: KVField[]
  onChange: (fields: KVField[]) => void
  addLabel?: string
}

/**
 * 精确计算字符展示宽度（中文算作 2ch，英文 1ch）
 */
const calcWidth = (str: string, fallbackLen = 4) => {
  if (!str) return fallbackLen + 1;
  let len = 0;
  for (let i = 0; i < str.length; i++) {
    len += str.charCodeAt(i) > 255 ? 2 : 1;
  }
  return Math.max(len, fallbackLen) + 1;
}

/**
 * 内联可编辑的「键:值」标签式字段。
 * Key 与 Value 都是无边框/虚线下划线的输入框，看起来干净但可编辑。
 */
export function InlineKeyValueFields({ fields, onChange, addLabel = "新增字段" }: InlineKeyValueFieldsProps) {
  const update = (id: number, patch: Partial<KVField>) =>
    onChange(fields.map((f) => (f.id === id ? { ...f, ...patch } : f)))

  const remove = (id: number) => onChange(fields.filter((f) => f.id !== id))

  const add = () => onChange([...fields, { id: nextKvId(), key: "新字段", value: "", valuePlaceholder: "填写内容" }])

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      {fields.map((field) => (
        <div
          key={field.id}
          className="group/kv flex items-center gap-1 rounded-md bg-muted/60 px-2 py-1 transition-colors hover:bg-muted"
        >
          <Input
            value={field.key || ""}
            onChange={(e) => update(field.id, { key: e.target.value })}
            className="h-6 w-auto min-w-10 max-w-[120px] border-0 bg-transparent px-0 text-xs font-medium text-muted-foreground shadow-none focus-visible:ring-0"
            style={{ width: `${calcWidth(field.key || "", 2)}ch` }}
            aria-label="字段名称"
          />
          <span className="text-xs text-muted-foreground/60">:</span>
          <Input
            value={field.value || ""}
            placeholder={field.valuePlaceholder}
            onChange={(e) => update(field.id, { value: e.target.value })}
            className="h-6 w-auto min-w-[80px] max-w-[500px] border-0 border-b border-dashed border-border/80 bg-transparent px-0 text-xs text-foreground shadow-none focus-visible:border-primary focus-visible:ring-0"
            style={{ width: `${calcWidth(field.value || "", field.valuePlaceholder?.length ? calcWidth(field.valuePlaceholder) : 6)}ch` }}
            aria-label="字段内容"
          />
          <Button
            size="icon"
            variant="ghost"
            className="h-5 w-5 shrink-0 text-muted-foreground/50 opacity-0 transition-opacity hover:text-destructive group-hover/kv:opacity-100"
            onClick={() => remove(field.id)}
          >
            <X className="h-3 w-3" />
            <span className="sr-only">删除字段</span>
          </Button>
        </div>
      ))}

      <Button
        size="sm"
        variant="ghost"
        className="h-6 gap-1 px-2 text-xs text-muted-foreground hover:text-foreground"
        onClick={add}
      >
        <Plus className="h-3 w-3" />
        {addLabel}
      </Button>
    </div>
  )
}
