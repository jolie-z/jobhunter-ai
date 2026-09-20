"use client"

import React from "react"
import { Check } from "lucide-react"
import { cn } from "@/lib/utils"

interface FailedJobCheckboxProps {
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  className?: string
  title?: string
}

export const FailedJobCheckbox = React.memo(function FailedJobCheckbox({
  checked,
  onChange,
  disabled = false,
  className,
  title = "选择此岗位",
}: FailedJobCheckboxProps) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      disabled={disabled}
      title={title}
      onClick={(e) => {
        e.stopPropagation()
        onChange(!checked)
      }}
      className={cn(
        "flex h-4.5 w-4.5 items-center justify-center rounded-md border transition-all duration-150 cursor-pointer select-none",
        checked
          ? "border-rose-600 bg-rose-600 text-white shadow-xs dark:border-rose-500 dark:bg-rose-500"
          : "border-border/80 bg-background/90 text-transparent hover:border-rose-400 hover:bg-rose-50/50 dark:hover:bg-rose-950/30",
        disabled && "opacity-40 cursor-not-allowed",
        className
      )}
    >
      <Check className={cn("h-3 w-3 stroke-[3]", checked ? "scale-100" : "scale-0 transition-transform")} />
    </button>
  )
})
