"use client"

import { useState, useMemo } from "react"
import { MapPin, Search, Check, ChevronDown, Sparkles } from "lucide-react"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { BOSS_HOT_CITIES, BOSS_CITY_GROUPS, SPECIAL_CITIES } from "../boss-cities"
import { cn } from "@/lib/utils"

interface CitySelectorPopoverProps {
  value: string
  onChange: (city: string) => void
  placeholder?: string
  className?: string
  buttonClassName?: string
}

export function CitySelectorPopover({
  value,
  onChange,
  placeholder = "选择城市",
  className,
  buttonClassName,
}: CitySelectorPopoverProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState("")
  const [activeLetter, setActiveLetter] = useState<string>("热门")

  const filteredGroups = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) {
      if (activeLetter === "热门") {
        return [{ group: "热门城市", cities: BOSS_HOT_CITIES }]
      }
      if (activeLetter === "全部") {
        return BOSS_CITY_GROUPS.filter((g) => g.group !== "热门")
      }
      return BOSS_CITY_GROUPS.filter((g) => g.group === activeLetter)
    }

    // 搜索模式：在所有城市中过滤
    const matched: string[] = []
    for (const group of BOSS_CITY_GROUPS) {
      for (const city of group.cities) {
        if (city.toLowerCase().includes(q) && !matched.includes(city)) {
          matched.push(city)
        }
      }
    }
    for (const spec of SPECIAL_CITIES) {
      if (spec.toLowerCase().includes(q) && !matched.includes(spec)) {
        matched.push(spec)
      }
    }
    return [{ group: `搜索「${q}」匹配结果 (${matched.length})`, cities: matched }]
  }, [search, activeLetter])

  const handleSelect = (city: string) => {
    onChange(city)
    setOpen(false)
    setSearch("")
  }

  const handleCustomInput = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== "Enter" || !search.trim()) return
    // 有匹配城市时回车优先选中第一个匹配项，仅无任何匹配才把原始输入当自定义城市
    const firstMatch = filteredGroups.flatMap((g) => g.cities)[0]
    handleSelect(firstMatch || search.trim())
  }

  const letterTabs = useMemo(() => {
    const letters = BOSS_CITY_GROUPS.filter((g) => g.group !== "热门").map((g) => g.group)
    return ["热门", "全部", ...letters]
  }, [])

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex items-center justify-between gap-1.5 rounded-lg border border-border/80 bg-background px-2.5 py-1.5 text-xs text-foreground font-medium shadow-xs transition-all hover:bg-muted/50 hover:border-violet-400 focus:outline-none focus:ring-1 focus:ring-violet-500",
            buttonClassName
          )}
        >
          <span className="flex items-center gap-1 truncate">
            <MapPin className="h-3.5 w-3.5 text-violet-500 shrink-0" />
            <span className={cn("truncate", !value && "text-muted-foreground")}>
              {value || placeholder}
            </span>
          </span>
          <ChevronDown className="h-3 w-3 text-muted-foreground shrink-0" />
        </button>
      </PopoverTrigger>

      <PopoverContent
        align="start"
        sideOffset={6}
        className={cn("w-80 p-3 shadow-xl rounded-xl border border-border bg-popover text-popover-foreground z-50", className)}
      >
        {/* 顶部搜索框 */}
        <div className="relative mb-2.5">
          <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={handleCustomInput}
            placeholder="搜索城市或输入回车自定义…"
            className="w-full rounded-lg border border-border bg-muted/40 pl-8 pr-3 py-1.5 text-xs focus:bg-background focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 transition-all"
          />
        </div>

        {/* 特殊范围与快捷选项 */}
        <div className="flex items-center gap-1 mb-2.5 pb-2 border-b border-border/60">
          <span className="text-[10px] text-muted-foreground shrink-0">范围:</span>
          {SPECIAL_CITIES.map((sp) => (
            <button
              key={sp}
              type="button"
              onClick={() => handleSelect(sp)}
              className={cn(
                "rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors",
                value === sp
                  ? "bg-violet-600 text-white font-bold"
                  : "bg-muted/60 text-foreground hover:bg-violet-500/10 hover:text-violet-600"
              )}
            >
              {sp}
            </button>
          ))}
        </div>

        {/* 字母索引栏（无搜索时展示） */}
        {!search && (
          <div className="flex flex-wrap gap-0.5 mb-2 pb-1.5 border-b border-border/50 max-h-12 overflow-y-auto">
            {letterTabs.map((letter) => (
              <button
                key={letter}
                type="button"
                onClick={() => setActiveLetter(letter)}
                className={cn(
                  "px-1.5 py-0.5 rounded text-[10px] font-mono transition-colors",
                  activeLetter === letter
                    ? "bg-violet-600 text-white font-bold"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                {letter}
              </button>
            ))}
          </div>
        )}

        {/* 城市列表展示区 */}
        <div className="max-h-52 overflow-y-auto space-y-2.5 pr-1">
          {filteredGroups.map((grp) => (
            <div key={grp.group} className="space-y-1">
              <div className="text-[10px] font-semibold text-muted-foreground font-mono">
                {grp.group}
              </div>
              <div className="flex flex-wrap gap-1">
                {grp.cities.map((city) => {
                  const isSelected = value === city
                  return (
                    <button
                      key={city}
                      type="button"
                      onClick={() => handleSelect(city)}
                      className={cn(
                        "inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] transition-all",
                        isSelected
                          ? "bg-violet-600 text-white font-semibold shadow-xs"
                          : "bg-muted/40 text-foreground hover:bg-violet-500/10 hover:text-violet-600 dark:hover:bg-violet-500/20"
                      )}
                    >
                      {city}
                      {isSelected && <Check className="h-2.5 w-2.5" />}
                    </button>
                  )
                })}
              </div>
            </div>
          ))}

          {filteredGroups.length === 0 || (filteredGroups.length === 1 && filteredGroups[0].cities.length === 0) ? (
            <div className="text-center py-4 text-xs text-muted-foreground space-y-2">
              <p>未找到该城市</p>
              {search.trim() && (
                <button
                  type="button"
                  onClick={() => handleSelect(search.trim())}
                  className="inline-flex items-center gap-1 rounded-md bg-violet-600/10 border border-violet-500/30 px-2.5 py-1 text-[11px] font-medium text-violet-600 hover:bg-violet-600 hover:text-white transition-colors"
                >
                  <Sparkles className="h-3 w-3" />
                  使用自定义城市「{search.trim()}」
                </button>
              )}
            </div>
          ) : null}
        </div>
      </PopoverContent>
    </Popover>
  )
}
