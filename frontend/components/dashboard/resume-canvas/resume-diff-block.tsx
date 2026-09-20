"use client"

import { useState, useEffect, useRef } from "react"
import {
  FileText,
  Lightbulb,
  ClipboardList,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  ChevronDown,
  Scissors,
  Sparkles,
  ArrowUp,
  ArrowDown,
  GripVertical,
} from "lucide-react"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { EditableSection } from "./editable-section"
import type { ResumeBlock } from "@/lib/resume-types"
import ReactMarkdown from 'react-markdown'

interface ReorderControls {
  onMoveUp: () => void
  onMoveDown: () => void
  canMoveUp: boolean
  canMoveDown: boolean
}

// 接收顶层传来的高亮和定位数据
interface ResumeDiffBlockProps extends ReorderControls {
  block: ResumeBlock
  moduleId: string
  findText: string
  matches: any[]
  currentMatchIndex: number
  isRaw?: boolean
  onChangeRewritten: (value: string) => void
  onChangeOriginal: (value: string) => void
}

export function ResumeDiffBlock({
  block,
  moduleId,
  findText,
  matches,
  currentMatchIndex,
  isRaw = false,
  onChangeRewritten,
  onChangeOriginal,
  onMoveUp,
  onMoveDown,
  canMoveUp,
  canMoveDown,
}: ResumeDiffBlockProps) {
  const reorder: ReorderControls = { onMoveUp, onMoveDown, canMoveUp, canMoveDown }

  if (block.mode === "editable") {
    return (
      <section className="rounded-xl border border-border bg-card p-4">
        <BlockHeader title={block.title} reorder={reorder} />
        <div className="mt-2 rounded-lg bg-white ring-1 ring-border">
          <EditableSection
            value={block.original}
            onChange={onChangeOriginal}
            placeholder="点击编辑教育背景…"
            // 传给底层渲染
            moduleId={moduleId}
            blockId={block.id}
            field="original"
            findText={findText}
            matches={matches}
            currentMatchIndex={currentMatchIndex}
          />
        </div>
      </section>
    )
  }

  if (block.mode === "cut") {
    return (
      <section className="rounded-xl border border-dashed border-red-200 bg-red-50/40 p-4">
        <div className="flex items-center gap-2">
          <Scissors className="size-4 text-red-500" />
          <h3 className="text-sm font-semibold text-slate-500 line-through decoration-red-300">{block.title}</h3>
          <div className="ml-auto flex items-center gap-1">
            <Badge variant="outline" className="border-red-200 bg-red-100 text-red-600">已裁剪</Badge>
            <ReorderControlsBar {...reorder} />
          </div>
        </div>
        <div className="mt-2 flex items-start gap-2 rounded-md bg-red-100/60 px-3 py-2">
          <XCircle className="mt-0.5 size-4 shrink-0 text-red-500" />
          <p className="text-sm leading-relaxed text-red-700">
            <span className="font-medium">裁剪理由：</span>{block.notes?.agent1.reason}
          </p>
        </div>
      </section>
    )
  }

  return (
    <section className="rounded-xl border border-border bg-slate-50/30 p-4 shadow-sm transition-all hover:shadow-md">
      <BlockHeader title={block.title} keep={!isRaw} reorder={reorder} />
      <div className={cn("mt-4 flex flex-col gap-4", !isRaw && "lg:grid lg:grid-cols-2")}>
        {!isRaw && (
          <div className="flex flex-col gap-2">
             <div className="flex items-center gap-1.5 px-1 py-0.5">
              <FileText className="size-3.5 text-slate-400" />
              <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                原始版本 (只读)
              </span>
            </div>
            <div className="h-full rounded-lg border border-slate-200/60 bg-slate-100/50 p-3 opacity-80 transition-opacity hover:opacity-100">
               <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-slate-500 line-through decoration-red-200/50">
                <HighlightedText text={block.original} moduleId={moduleId} blockId={block.id} field="original" findText={findText} matches={matches} currentMatchIndex={currentMatchIndex} />
              </p>
            </div>
          </div>
        )}
        
        <div className="flex flex-col gap-2">
          <FinalLayer
            value={isRaw ? block.original : (block.rewritten ?? "")}
            onChange={isRaw ? onChangeOriginal : onChangeRewritten}
            moduleId={moduleId} blockId={block.id}
            findText={findText} matches={matches} currentMatchIndex={currentMatchIndex}
            isRaw={isRaw}
            notes={!isRaw ? block.notes : undefined}
          />
        </div>
      </div>
    </section>
  )
}

function BlockHeader({ title, keep, reorder }: any) {
  return (
    <div className="flex items-center gap-2">
      <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
      <div className="ml-auto flex items-center gap-1">
        {keep && <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-600">保留并改写</Badge>}
        {reorder && <ReorderControlsBar {...reorder} />}
      </div>
    </div>
  )
}

function ReorderControlsBar({ onMoveUp, onMoveDown, canMoveUp, canMoveDown }: ReorderControls) {
  return (
    <div className="flex items-center">
      <Button variant="ghost" size="sm" className="size-7 cursor-grab px-0 text-slate-300 hover:text-slate-500 active:cursor-grabbing"><GripVertical className="size-4" /></Button>
      <Button variant="ghost" size="sm" className="size-7 px-0 text-slate-400 hover:text-slate-700 disabled:opacity-30" disabled={!canMoveUp} onClick={onMoveUp}><ArrowUp className="size-4" /></Button>
      <Button variant="ghost" size="sm" className="size-7 px-0 text-slate-400 hover:text-slate-700 disabled:opacity-30" disabled={!canMoveDown} onClick={onMoveDown}><ArrowDown className="size-4" /></Button>
    </div>
  )
}

// 🌟 核心渲染引擎：将文本切片并渲染高亮，如果是当前匹配项则挂载滚动 ref
function HighlightedText({ text, moduleId, blockId, field, findText, matches, currentMatchIndex }: any) {
  const currentMatchRef = useRef<HTMLElement>(null);

  useEffect(() => {
    // 当 currentMatchIndex 改变时，如果当前组件包含对应的 ref，则平滑滚动到视野中
    if (currentMatchRef.current) {
      currentMatchRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [currentMatchIndex]);

  if (!findText) return <>{text}</>;

  const parts = text.split(new RegExp(`(${findText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'));
  let localMatchCounter = 0; // 用于在这个文本块内计算是第几个匹配项

  // 计算当前块在所有 matches 中的起始绝对索引
  const blockMatchesStartIdx = matches.findIndex((m: any) => m.moduleId === moduleId && m.blockId === blockId && m.field === field);

  return (
    <>
      {parts.map((part: string, index: number) => {
        if (part.toLowerCase() === findText.toLowerCase()) {
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

function OriginalLayer({ text, moduleId, blockId, findText, matches, currentMatchIndex }: any) {
  const [open, setOpen] = useState(true)

  // 如果搜索词在闭合状态下被匹配到了，强制展开
  useEffect(() => {
    if (findText && text.toLowerCase().includes(findText.toLowerCase())) {
      setOpen(true)
    }
  }, [findText, text])

  return (
    <div className="rounded-lg border border-slate-100 bg-slate-50/50">
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex w-full items-center gap-2 px-3 py-1.5 text-left">
        <FileText className="size-3.5 text-slate-400" />
        <span className="text-[11px] font-medium uppercase tracking-wide text-slate-400">原始版本</span>
        <ChevronDown className={cn("ml-auto size-3.5 text-slate-300 transition-transform", !open && "-rotate-90")} />
      </button>
      {open && (
        <p className="whitespace-pre-wrap px-3 pb-2.5 text-[13px] leading-relaxed text-slate-400">
          <HighlightedText text={text} moduleId={moduleId} blockId={blockId} field="original" findText={findText} matches={matches} currentMatchIndex={currentMatchIndex} />
        </p>
      )}
    </div>
  )
}

function AiNotesLayer({ notes }: any) {
  if (!notes) return null
  const { agent1, agent2, agent3 } = notes
  return (
    <div className="rounded-lg border-l-4 border-indigo-400 bg-indigo-50/50 px-3 py-2.5">
      <div className="mb-2 flex items-center gap-1.5"><Sparkles className="size-3.5 text-indigo-500" /><span className="text-[11px] font-semibold uppercase tracking-wide text-indigo-500">AI 改写批注</span></div>
      <div className="flex flex-col gap-2.5 text-[13px] leading-relaxed">
        {agent1 && (<div><p className="text-indigo-900"><span className="font-medium">保留理由：</span>{agent1.reason}</p>{agent1.matchedPoints && agent1.matchedPoints.length > 0 && (<div className="mt-1 flex flex-wrap gap-1">{agent1.matchedPoints.map((p: string) => (<span key={p} className="rounded bg-indigo-100 px-1.5 py-0.5 text-[11px] text-indigo-700">命中 JD · {p}</span>))}</div>)}</div>)}
        {agent2 && (
          <div className="rounded-md bg-white/60 p-2">
            <div className="flex items-start gap-1.5 text-indigo-900">
              <Lightbulb className="mt-0.5 size-3.5 shrink-0 text-amber-500" />
              <div className="flex-1 w-full overflow-hidden">
                <span className="font-medium text-[13px]">重写逻辑：</span>
                <div className="prose prose-sm prose-slate max-w-none text-[13px] text-indigo-900 prose-p:my-1 prose-ul:my-1 prose-li:my-0.5 mt-1">
                  <ReactMarkdown>{agent2.logic}</ReactMarkdown>
                </div>
              </div>
            </div>
            {agent2.dataRequests.length > 0 && (
              <div className="mt-2 flex flex-col gap-1">
                {agent2.dataRequests.map((req: string) => (
                  <p key={req} className="flex items-start gap-1.5 rounded bg-amber-50 px-2 py-1 text-amber-700">
                    <ClipboardList className="mt-0.5 size-3.5 shrink-0" />
                    <span><span className="font-medium">待补充：</span>{req}</span>
                  </p>
                ))}
              </div>
            )}
          </div>
        )}
        {agent3 && (<p className={cn("flex items-start gap-1.5 rounded-md px-2 py-1.5", agent3.status === "pass" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700")}>{agent3.status === "pass" ? (<CheckCircle2 className="mt-0.5 size-3.5 shrink-0" />) : (<AlertTriangle className="mt-0.5 size-3.5 shrink-0" />)}<span><span className="font-medium">QA 审核：</span>{agent3.message}</span></p>)}
      </div>
    </div>
  )
}

function FinalLayer({ value, onChange, moduleId, blockId, findText, matches, currentMatchIndex, isRaw, notes }: any) {
  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex items-center justify-between px-1 py-0.5">
        <div className="flex items-center gap-1.5">
          <Sparkles className={cn("size-3.5", isRaw ? "text-blue-500" : "text-violet-500")} />
          <span className={cn("text-[11px] font-bold uppercase tracking-wide", isRaw ? "text-slate-600" : "text-violet-600")}>
            {isRaw ? "原始简历 · 可编辑" : "AI 专属重构版"}
          </span>
        </div>
        
        {!isRaw && notes && (
           <AiPopoverNote notes={notes} />
        )}
      </div>
      
      <div className="h-full rounded-lg bg-white shadow-sm ring-1 ring-violet-100 transition-all focus-within:ring-violet-300 hover:shadow">
        <EditableSection
          value={value} onChange={onChange}
          placeholder={isRaw ? "原始简历内容，点击即可编辑…" : "最终改写内容，点击即可编辑…"}
          moduleId={moduleId} blockId={blockId} field={isRaw ? "original" : "rewritten"}
          findText={findText} matches={matches} currentMatchIndex={currentMatchIndex}
        />
      </div>
    </div>
  )
}

function AiPopoverNote({ notes }: { notes: any }) {
  if (!notes) return null
  const { agent1, agent2, agent3 } = notes
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="h-6 gap-1 rounded-full border-violet-200 bg-violet-50 px-2 text-[10px] text-violet-700 hover:bg-violet-100 hover:text-violet-800">
          <Lightbulb className="size-3" />
          <span>Why?</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[340px] rounded-xl border border-indigo-100 bg-white/95 p-0 shadow-xl backdrop-blur-md">
         <div className="border-b border-indigo-50 bg-gradient-to-r from-indigo-50/50 to-white px-4 py-3">
          <div className="flex items-center gap-1.5">
            <Sparkles className="size-4 text-indigo-500" />
            <span className="text-[12px] font-bold text-indigo-900">Agent 改写脑图</span>
          </div>
         </div>
         <div className="flex max-h-[300px] flex-col gap-3 overflow-y-auto p-4 text-[13px] leading-relaxed">
            {agent1 && (
              <div>
                <p className="text-slate-700"><span className="font-semibold text-slate-900">🎯 打捞决策：</span>{agent1.reason}</p>
              </div>
            )}
            {agent2 && (
              <div className="rounded-lg bg-slate-50 p-3">
                <p className="font-semibold text-slate-900 mb-1">🧠 重构逻辑：</p>
                <div className="prose prose-sm prose-slate max-w-none text-[12px] text-slate-600 prose-p:my-1 prose-ul:my-1">
                  <ReactMarkdown>{agent2.logic}</ReactMarkdown>
                </div>
              </div>
            )}
         </div>
      </PopoverContent>
    </Popover>
  )
}