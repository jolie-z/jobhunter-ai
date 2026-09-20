"use client"

import { useState, useEffect, useRef } from "react"
import { Textarea } from "@/components/ui/textarea"
import { API_BASE } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Bot, Flame, Mic, RefreshCw, Sparkles, Trash2, Target, Wand2, Loader2 } from "lucide-react"
import { InlineKeyValueFields, type KVField, nextKvId } from "./inline-key-value-fields"
import { ExperienceGriller } from "./experience-griller"
import { AtsAligner } from "./ats-aligner"
import { MarkdownEditor } from "./markdown-editor"
import { AiModuleSyncInline } from "./ai-module-sync-inline"
import { useStrategyStore, type ResumeSubModule } from "@/hooks/use-strategy-store"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import { toast } from "@/hooks/use-toast"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"

interface ExperienceItemProps {
  item: any
  index: number
  type: 'workExperience' | 'personalProjects' | 'education' | 'custom'
  moduleKey?: string
  onUpdate: (patch: any) => void
  wizardStep?: string
  grillQueue?: string[]
  atsQueue?: string[]
  syncQueue?: string[]
  onWizardComplete?: (tool: string, sectionId?: string) => void
  onDelete: () => void
  canMoveUp?: boolean
  canMoveDown?: boolean
  onMoveUp?: () => void
  onMoveDown?: () => void
}


// 条目标准字段的 key；其余原始类型 key 视为用户通过「新增字段」添加的自定义 KV 字段。
// id 与 _key 为运行时标识（sectionId 兜底用到 id），绝不能作为可编辑 KV 暴露
const ITEM_STANDARD_KEYS = new Set([
  "company", "title", "years", "name", "role", "institution", "major", "degree",
  "description", "originalContent", "_key", "id",
])

function extractExtraKvFields(item: Record<string, any> | null | undefined): Array<{ key: string; value: string }> {
  if (!item) return []
  return Object.entries(item)
    .filter(([, v]) => v !== null && v !== undefined && typeof v !== "object")
    .filter(([k]) => !ITEM_STANDARD_KEYS.has(k))
    .map(([k, v]) => ({ key: k, value: String(v) }))
}

// Set to keep track of items that have completed grilling to prevent auto-reopen on remount
const completedGrillSet = new Set<string>()

export function ExperienceItem({ item, index, type, moduleKey, onUpdate, onDelete, canMoveUp, canMoveDown, onMoveUp, onMoveDown, wizardStep, onWizardComplete, atsQueue, syncQueue, grillQueue }: ExperienceItemProps) {
  const { resumeData } = useResumeV2Store()
  
  const [grillOpen, setGrillOpen] = useState(false)
  const [atsOpen, setAtsOpen] = useState(false)
  const [aiSyncOpen, setAiSyncOpen] = useState(false)
  const [isFormatting, setIsFormatting] = useState(false)
  const [fields, setFields] = useState<KVField[]>([])

  // Compute the correct sectionId that matches the GrillSuggestionPanel logic
  const sectionId = type === 'workExperience' ? `work-${index}` 
    : type === 'personalProjects' ? `project-${index}` 
    : type === 'education' ? `edu-${index}`
    : moduleKey ? `${moduleKey}-${index}` : item.id;

  // --- 向导步骤联动（拆分为两个 effect，修复手动打开面板被回弹关闭的缺陷）---
  const lastAutoStartedStep = useRef<string | null>(null)
  const prevWizardStepRef = useRef<string | null | undefined>(null)

  // ① 步骤切换清理：仅在 wizardStep 实际变化时执行一次；
  // 面板开关状态不进依赖，用户手动点开的面板绝不会被这里回弹
  useEffect(() => {
    if (prevWizardStepRef.current === wizardStep) return
    prevWizardStepRef.current = wizardStep
    lastAutoStartedStep.current = null
    if (!wizardStep || wizardStep === 'idle') {
      setGrillOpen(false);
      setAtsOpen(false);
      setAiSyncOpen(false);
      return;
    }
    if (wizardStep !== 'step3') setGrillOpen(false);
    if (wizardStep !== 'step4') setAtsOpen(false);
    if (wizardStep !== 'step5') setAiSyncOpen(false);
  }, [wizardStep])

  // ② 向导队列自动打开：只监听步骤与队列变化；点击处理器中的 setXxxOpen 不再触发本 effect
  useEffect(() => {
    if (!wizardStep || wizardStep === 'idle') return

    // Step 3 Grill 队列逻辑（已完成拷打的条目不自动重开，手动点击不受影响）
    if (wizardStep === 'step3' && grillQueue?.[0] === sectionId && !grillOpen && !completedGrillSet.has(compositeKey)) {
      lastAutoStartedStep.current = wizardStep;
      setGrillOpen(true);
    }

    // Step 4 ATS 队列并发控制逻辑（每次最多处理 3 个）
    if (wizardStep === 'step4' && atsQueue?.slice(0, 3).includes(sectionId) && !atsOpen) {
      lastAutoStartedStep.current = wizardStep;
      setAtsOpen(true);
    }

    // Step 5 Sync 队列并发控制逻辑（每次最多处理 3 个）
    if (wizardStep === 'step5' && syncQueue?.slice(0, 3).includes(sectionId) && !aiSyncOpen) {
      lastAutoStartedStep.current = wizardStep;
      setAiSyncOpen(true);
    }
  }, [wizardStep, grillQueue, atsQueue, syncQueue, sectionId]) // eslint-disable-line react-hooks/exhaustive-deps
  
  // Calculate a composite string to detect external changes（含自定义 KV 字段，保证外部改动也能刷新表单）
  const compositeKey = JSON.stringify([
    item.company, item.name, item.institution, item.title, item.role, item.major, item.degree, item.years,
    extractExtraKvFields(item),
  ])

  useEffect(() => {
    let newFields: KVField[] = []
    let fid = 100
    if (type === 'workExperience') {
      newFields = [
        { id: ++fid, key: "公司", value: item.company || "", valuePlaceholder: "公司名称" },
        { id: ++fid, key: "职位", value: item.title || "", valuePlaceholder: "职位" },
        { id: ++fid, key: "时间", value: item.years || "", valuePlaceholder: "如: 2020-2023" }
      ]
    } else if (type === 'personalProjects') {
      newFields = [
        { id: ++fid, key: "项目", value: item.name || "", valuePlaceholder: "项目名称" },
        { id: ++fid, key: "角色", value: item.role || "", valuePlaceholder: "角色" },
        { id: ++fid, key: "时间", value: item.years || "", valuePlaceholder: "如: 2020-2023" }
      ]
    } else if (type === 'education') {
      newFields = [
        { id: ++fid, key: "学校", value: item.institution || "", valuePlaceholder: "学校名称" },
        { id: ++fid, key: "专业", value: item.major || "", valuePlaceholder: "专业名称" },
        { id: ++fid, key: "学历", value: item.degree || "", valuePlaceholder: "学历" },
        { id: ++fid, key: "时间", value: item.years || "", valuePlaceholder: "如: 2020-2023" }
      ]
    }
    // 追加用户自定义 KV 字段（第 4+ 列），确保「新增字段」的内容在重挂载后依然可见
    extractExtraKvFields(item).forEach(extra => {
      newFields.push({ id: ++fid, key: extra.key, value: extra.value })
    })
    setFields(newFields)
  }, [compositeKey])

  const notifyChange = (newFields: KVField[]) => {
    setFields(newFields)
    const patch: any = {}
    if (type === 'workExperience') {
      patch.company = newFields[0]?.value || ""
      patch.title = newFields[1]?.value || ""
      patch.years = newFields[2]?.value || ""
    } else if (type === 'personalProjects') {
      patch.name = newFields[0]?.value || ""
      patch.role = newFields[1]?.value || ""
      patch.years = newFields[2]?.value || ""
    } else if (type === 'education') {
      patch.institution = newFields[0]?.value || ""
      patch.major = newFields[1]?.value || ""
      patch.degree = newFields[2]?.value || ""
      patch.years = newFields[3]?.value || ""
    }

    // 自定义 KV 字段持久化：以字段名作为条目上的额外 key 写入 patch；
    // 已删除或改名的旧 key 置 undefined 抹除，杜绝「UI 可填但不保存」的数据黑洞
    const standardFieldCount = type === 'education' ? 4 : type === 'custom' ? 0 : 3
    const seenExtraKeys = new Set<string>()
    newFields.slice(standardFieldCount).forEach(f => {
      const k = (f.key || "").trim()
      // 守卫：字段名撞标准键（如 description/company）时拒绝写入，防止覆盖条目核心字段
      if (!k || seenExtraKeys.has(k) || ITEM_STANDARD_KEYS.has(k)) return
      seenExtraKeys.add(k)
      patch[k] = f.value
    })
    extractExtraKvFields(item).forEach(({ key }) => {
      if (!seenExtraKeys.has(key)) patch[key] = undefined
    })

    onUpdate(patch)
  }

  const contentText = Array.isArray(item.description) ? item.description.join('\n') : (item.description || "")
  const handleContentChange = (val: string) => {
    onUpdate({ description: type === 'education' ? val : val.split('\n') })
  }

  const handleFormatMarkdown = async () => {
    if (!contentText.trim()) {
      toast({ title: "提示", description: "当前条目还没有内容，先填写描述再排版" })
      return
    }
    setIsFormatting(true)
    try {
      const res = await fetch(`${API_BASE}/api/strategy/format_markdown`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ module_title: item.institution || item.name || item.company || "自定义条目", current_content: contentText })
      })
      const data = await res.json()
      if (data.status === "success" && data.data?.formatted_content) {
        handleContentChange(data.data.formatted_content)
      } else {
        toast({ variant: "destructive", title: "❌ 自动排版失败", description: data.message || "后端排版接口返回异常" })
      }
    } catch (e) {
      console.error("Format markdown failed:", e)
      toast({ variant: "destructive", title: "❌ 自动排版失败", description: "网络请求异常，请检查后端服务" })
    } finally {
      setIsFormatting(false)
    }
  }

  return (
    <div data-section-id={sectionId} className="rounded-xl border border-border/70 bg-card p-4 transition-colors hover:border-border">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <InlineKeyValueFields fields={fields} onChange={notifyChange} />
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          {onMoveUp && (
            <Button
              size="icon"
              variant="ghost"
              disabled={!canMoveUp}
              className="h-8 w-8 text-muted-foreground hover:text-foreground disabled:opacity-30"
              onClick={onMoveUp}
            >
              <svg width="15" height="15" viewBox="0 0 15 15" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M7.14645 2.14645C7.34171 1.95118 7.65829 1.95118 7.85355 2.14645L11.8536 6.14645C12.0488 6.34171 12.0488 6.65829 11.8536 6.85355C11.6583 7.04882 11.3417 7.04882 11.1464 6.85355L8 3.70711L8 12.5C8 12.7761 7.77614 13 7.5 13C7.22386 13 7 12.7761 7 12.5L7 3.70711L3.85355 6.85355C3.65829 7.04882 3.34171 7.04882 3.14645 6.85355C2.95118 6.65829 2.95118 6.34171 3.14645 6.14645L7.14645 2.14645Z" fill="currentColor" fillRule="evenodd" clipRule="evenodd"></path></svg>
            </Button>
          )}
          {onMoveDown && (
            <Button
              size="icon"
              variant="ghost"
              disabled={!canMoveDown}
              className="h-8 w-8 text-muted-foreground hover:text-foreground disabled:opacity-30"
              onClick={onMoveDown}
            >
              <svg width="15" height="15" viewBox="0 0 15 15" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M7.5 2C7.77614 2 8 2.22386 8 2.5L8 11.2929L11.1464 8.14645C11.3417 7.95118 11.6583 7.95118 11.8536 8.14645C12.0488 8.34171 12.0488 8.65829 11.8536 8.85355L7.85355 12.8536C7.75979 12.9473 7.63261 13 7.5 13C7.36739 13 7.24021 12.9473 7.14645 12.8536L3.14645 8.85355C2.95118 8.65829 2.95118 8.34171 3.14645 8.14645C3.34171 7.95118 3.65829 7.95118 3.85355 8.14645L7 11.2929L7 2.5C7 2.22386 7.22386 2 7.5 2Z" fill="currentColor" fillRule="evenodd" clipRule="evenodd"></path></svg>
            </Button>
          )}
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8 text-muted-foreground hover:text-destructive"
              >
                <Trash2 className="h-4 w-4" />
                <span className="sr-only">删除经历</span>
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>确认删除这条经历？</AlertDialogTitle>
                <AlertDialogDescription>
                  删除后无法撤销，该条目中的所有信息将永久丢失。
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>取消</AlertDialogCancel>
                <AlertDialogAction onClick={onDelete}>
                  确认删除
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      <MarkdownEditor 
        value={contentText} 
        onChange={handleContentChange}
        placeholder="填写详细经历（支持 Markdown）"
        minHeight="min-h-[120px]"
      />

      <div className="flex items-center justify-end gap-2 border-t border-border/40 pt-2">
        <Button
          variant="outline"
          size="sm"
          disabled={isFormatting}
          className="h-8 text-xs bg-amber-50 text-amber-600 hover:bg-amber-100 border border-amber-200 shadow-sm transition-all"
          onClick={handleFormatMarkdown}
        >
          {isFormatting ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5 mr-1.5" />}
          {isFormatting ? "排版中..." : "自动排版"}
        </Button>
        {(type === 'workExperience' || type === 'personalProjects') ? (
          <>
            <Button
              onClick={() => {
                setAtsOpen((v) => !v)
                if (grillOpen) setGrillOpen(false)
                if (aiSyncOpen) setAiSyncOpen(false)
              }}
              className="bg-blue-600 hover:bg-blue-700 text-white shadow-sm transition-all hover:shadow-md"
              size="sm"
            >
              <Target className="mr-1.5 h-4 w-4" />
              ATS 靶向预写
            </Button>
            <Button
              onClick={() => {
                setGrillOpen((v) => !v)
                if (atsOpen) setAtsOpen(false)
                if (aiSyncOpen) setAiSyncOpen(false)
              }}
              className="bg-gradient-to-r from-orange-500 to-rose-500 text-white shadow-sm transition-all hover:from-orange-600 hover:to-rose-600 hover:shadow-md"
              size="sm"
            >
              <Flame className="mr-1.5 h-4 w-4" />
              Grill-me 深度拷打
            </Button>
          </>
        ) : (
          <Button 
            variant="secondary" 
            size="sm" 
            className="h-8 text-xs bg-indigo-50 text-indigo-600 hover:bg-indigo-100 border border-indigo-200 shadow-sm transition-all"
            onClick={() => {
              setAiSyncOpen(!aiSyncOpen)
              if (atsOpen) setAtsOpen(false)
              if (grillOpen) setGrillOpen(false)
            }}
          >
            <Sparkles className="h-3.5 w-3.5 mr-1.5" />
            {aiSyncOpen ? "收起联动更新" : "AI 联动更新"}
          </Button>
        )}
      </div>

      {aiSyncOpen && (type !== 'workExperience' && type !== 'personalProjects') && (
        <div className="mt-3">
          <AiModuleSyncInline
            moduleTitle={item.institution || item.name || "自定义条目"}
            currentContent={contentText}
            experiencesContext={JSON.stringify({
              workExperience: resumeData?.workExperience,
              personalProjects: resumeData?.personalProjects
            })}
            onAccept={(newContent) => {
              handleContentChange(newContent)
              setAiSyncOpen(false)
              if (onWizardComplete) onWizardComplete('sync_item_done', sectionId)
            }}
            onCancel={() => {
              setAiSyncOpen(false)
              if (onWizardComplete) onWizardComplete('sync_item_cancel', sectionId)
            }}
          />
        </div>
      )}

      {atsOpen ? (
        <AtsAligner 
          originalExperience={`[${fields.map(f=>f.value).join(' · ')}]\n${contentText}`}
          onAccept={(newContent) => {
            let cleanNewContent = newContent
            const titleMatch = newContent.match(/^\[(.*?)\]\n([\s\S]*)/)
            if (titleMatch) cleanNewContent = titleMatch[2]
            handleContentChange(cleanNewContent.trim())
            setAtsOpen(false)
            if (onWizardComplete) onWizardComplete('ats_item_done', sectionId)
          }}
          onCancel={() => {
            setAtsOpen(false)
            if (onWizardComplete) onWizardComplete('ats_item_cancel', sectionId)
          }}
        />
      ) : null}

      {grillOpen ? (  /* 已完成拷打的条目也允许手动重开（completedGrillSet 仅拦截向导队列自动打开） */
        <ExperienceGriller 
          originalExperience={`[${fields.map(f=>f.value).join(' · ')}]\n${contentText}`} 
          onAccept={(newContent) => {
            let cleanNewContent = newContent
            const titleMatch = newContent.match(/^\[(.*?)\]\n([\s\S]*)/)
            if (titleMatch) cleanNewContent = titleMatch[2]
            
            // Mark this item as completed so it doesn't auto-open again if remounted
            const currentCompositeKey = JSON.stringify([item.company, item.name, item.institution, item.title, item.role, item.major, item.degree, item.years])
            completedGrillSet.add(currentCompositeKey)

            handleContentChange(cleanNewContent.trim())
            setGrillOpen(false)
            if (onWizardComplete) onWizardComplete('grill_item_done', sectionId)
          }}
          onCancel={() => setGrillOpen(false)}
        />
      ) : null}
    </div>
  )
}

export { nextKvId }
