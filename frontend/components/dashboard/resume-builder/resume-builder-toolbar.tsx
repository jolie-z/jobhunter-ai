"use client"

// 简历库顶部工具栏（从 resume-builder/index.tsx 拆出，Q-M4-6 行数治理）
// 名称行内编辑 / 生效徽章 / 全局排版 / 导入 / JD画像 / Skill 中枢岛屿 / 预览 / 图片·PDF 导出 / 保存
// store 状态直接内部消费（R1 审查 P2：避免 24 个扁平 props 的 Data Clumps）

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { JdReportDialog } from "./jd-report-dialog"
import { SkillSelector } from "@/components/skill-selector"
import { PdfPreviewDialog } from "../features/v2-resume-editor/components/pdf-preview-dialog"
import { useStrategyStore } from "@/hooks/use-strategy-store"
import type { ResumeBuilderActions } from "./use-resume-builder-actions"
import {
  FileText, Loader2, Save, FileDown, Upload, RefreshCw, Eye, Sparkles, Image as ImageIcon, Paintbrush, FolderArchive
} from 'lucide-react'

type ResumeBuilderToolbarProps = {
  actions: ResumeBuilderActions
  selectedSkill: string | null
  onSelectSkill: (skill: string | null) => void
  previewOpen: boolean
  setPreviewOpen: (open: boolean) => void
  onOpenArtifacts: () => void
}

// 导出下拉数据驱动配置（R1 审查 P2：消除图片/PDF 两段镜像 JSX）
const EXPORT_MENUS = [
  {
    key: "images" as const,
    label: "保存图片",
    busyLabel: "生成中...",
    icon: ImageIcon,
    triggerIconClass: "text-pink-500 group-hover:text-pink-600",
    items: [
      { template: "classic" as const, label: "图片 · 普通模版", itemIcon: ImageIcon, itemIconClass: "text-sky-500" },
      { template: "color" as const, label: "图片 · 彩色模版", itemIcon: ImageIcon, itemIconClass: "text-indigo-500" },
    ],
  },
  {
    key: "pdf" as const,
    label: "保存 PDF",
    busyLabel: "生成中...",
    icon: FileDown,
    triggerIconClass: "text-emerald-500 group-hover:text-emerald-600",
    items: [
      { template: "classic" as const, label: "PDF · 普通模版", itemIcon: FileDown, itemIconClass: "text-rose-500" },
      { template: "color" as const, label: "PDF · 彩色模版", itemIcon: FileDown, itemIconClass: "text-blue-600" },
    ],
  },
]

export function ResumeBuilderToolbar(props: ResumeBuilderToolbarProps) {
  const { actions, selectedSkill, onSelectSkill, previewOpen, setPreviewOpen, onOpenArtifacts } = props
  const {
    editingItem, togglingResumeId, handleToggleResumeStatus,
    saving, handleSave,
    isParsing, fileInputRef, handleFileImport,
    setEditingItem, setResumes, markDirty
  } = useStrategyStore()

  const activeName = editingItem?.name || "简历"

  // 🌟 顶部简历名称编辑状态控制（自包含：仅本工具栏消费）
  const [isEditingName, setIsEditingName] = useState(false)
  const [nameDraft, setNameDraft] = useState("")

  // 当切换简历时，实时同步草稿名字
  useEffect(() => {
    if (editingItem?.name) {
      setNameDraft(editingItem.name)
    }
  }, [editingItem?.record_id, editingItem?.name])

  // 🌟 处理右侧顶部简历名称修改并乐观同步到左侧导航栏
  const handleSaveName = () => {
    if (nameDraft.trim() && editingItem) {
      const newName = nameDraft.trim()
      if (newName !== editingItem.name) markDirty()
      setEditingItem({ ...editingItem, name: newName })
      // 🌟 不可变同步到全局 resumes，让左侧导航栏热刷新
      setResumes(prev => prev.map(r => (r.record_id === editingItem.record_id ? { ...r, name: newName } : r)))
    }
    setIsEditingName(false)
  }

  return (
    <header className="sticky top-0 z-20 shrink-0 border-b border-border bg-background/80 backdrop-blur-md">
      <div className="flex items-center justify-between gap-4 px-5 py-3.5">
        <div className="flex min-w-0 items-center gap-2 flex-1">
          <FileText className="h-5 w-5 shrink-0 text-primary" />
          {isEditingName ? (
            <div className="flex items-center gap-1.5">
              <input
                value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                onBlur={handleSaveName}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleSaveName()
                  if (e.key === "Escape") setIsEditingName(false)
                }}
                className="h-8 w-48 rounded-md border border-input bg-background px-2 py-1 text-sm font-semibold focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
                autoFocus
              />
            </div>
          ) : (
            <div
              className="group flex min-w-0 items-center gap-2 cursor-pointer rounded px-1.5 py-0.5 hover:bg-muted/60 transition-colors"
              onClick={() => { setNameDraft(activeName); setIsEditingName(true); }}
            >
              <h1 className="truncate text-base font-semibold tracking-tight text-foreground sm:text-lg">
                {activeName}
              </h1>
              <span className="opacity-0 group-hover:opacity-100 text-xs text-muted-foreground transition-opacity">✏️</span>
            </div>
          )}

          {/* 🌟 飞书云端状态联动徽章与操作按钮 */}
          {editingItem?.status === '启用' || editingItem?.status === '启用中' ? (
            <div className="flex shrink-0 items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-100 border border-emerald-200 ml-2 select-none whitespace-nowrap">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500"></span>
              </span>
              <span className="text-[10px] font-bold text-emerald-700">当前生效</span>
            </div>
          ) : (
            <Button
              variant="outline"
              size="sm"
              className="ml-1 h-6 shrink-0 px-2 text-[11px] font-medium text-muted-foreground hover:text-emerald-600 hover:border-emerald-300 hover:bg-emerald-50 transition-all shadow-none"
              disabled={togglingResumeId === editingItem?.record_id || !editingItem?.record_id}
              onClick={(e) => editingItem && handleToggleResumeStatus(e, editingItem)}
            >
              {togglingResumeId === editingItem?.record_id ? "切换中..." : "设为生效"}
            </Button>
          )}
        </div>
        {/* Apple Minimalist Toolbar */}
        <div className="flex items-center gap-1 shrink-0 p-1 rounded-xl bg-secondary/40 border border-border/40 backdrop-blur-md shadow-sm">
          <div className="flex items-center gap-0.5">
            <Button
              variant="ghost"
              size="sm"
              className="group h-8 px-2 hover:px-2.5 text-muted-foreground hover:bg-background hover:shadow-sm rounded-lg transition-all duration-300 ease-out flex items-center"
              onClick={actions.handleGlobalFormat}
              disabled={actions.isGlobalFormatting}
              title="一键自动排版全文"
            >
              {actions.isGlobalFormatting ? <Loader2 className="h-4 w-4 shrink-0 animate-spin text-amber-500" /> : <Paintbrush className="h-4 w-4 shrink-0 text-amber-500 group-hover:text-amber-600 transition-colors" />}
              <span className="max-w-0 overflow-hidden opacity-0 group-hover:max-w-[100px] group-hover:opacity-100 group-hover:ml-1.5 text-[13px] font-medium whitespace-nowrap text-foreground transition-all duration-300 ease-out">
                {actions.isGlobalFormatting ? actions.globalFormatProgress : '全局排版'}
              </span>
            </Button>

            {/* M2 口径修正：accept 补齐 .doc（store 白名单本就接受 application/msword） */}
            <input type="file" accept=".pdf,.doc,.docx" ref={fileInputRef} className="hidden" onChange={handleFileImport} />
            <Button
              variant="ghost"
              size="sm"
              className="group h-8 px-2 hover:px-2.5 text-muted-foreground hover:bg-background hover:shadow-sm rounded-lg transition-all duration-300 ease-out flex items-center"
              onClick={() => fileInputRef.current?.click()}
              disabled={isParsing}
              title="支持 PDF / Word"
            >
              {isParsing ? <RefreshCw className="h-4 w-4 shrink-0 animate-spin text-blue-500" /> : <Upload className="h-4 w-4 shrink-0 text-blue-500 group-hover:text-blue-600 transition-colors" />}
              <span className="max-w-0 overflow-hidden opacity-0 group-hover:max-w-[100px] group-hover:opacity-100 group-hover:ml-1.5 text-[13px] font-medium whitespace-nowrap text-foreground transition-all duration-300 ease-out">
                {isParsing ? '解析中...' : '简历导入'}
              </span>
            </Button>

            <JdReportDialog />
          </div>

          <div className="w-[1px] h-4 bg-border/50 mx-1.5" />

          {/* 🌟 2️⃣ Skill 智能体作战中枢 (与定制面板 1:1 完整一致的组合岛屿) */}
          <div className="flex items-center gap-1.5 bg-gradient-to-r from-amber-50/95 via-orange-50/80 to-amber-50/95 border border-amber-300/80 shadow-xs ring-1 ring-amber-400/25 rounded-xl p-0.5 px-1.5 shrink-0">
            {/* 剧本选择器 (支持切换官方/自定义，点击 ℹ️ 呼出 References 资料清单弹窗，点击自定义呼出上传弹窗) */}
            <SkillSelector
              selectedSkill={selectedSkill}
              onChange={onSelectSkill}
              compact={true}
              className="h-6.5 text-xs border-0 bg-transparent shadow-none"
            />

            {/* 主行动按钮：✨ 执行改写 */}
            <Button
              size="sm"
              className="h-6.5 px-2.5 text-xs font-semibold bg-gradient-to-r from-amber-500 via-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white rounded-lg shadow-xs active:scale-[0.97] transition-all flex items-center gap-1"
              onClick={actions.handleSkillRewrite}
              disabled={actions.isTestingSkill}
            >
              {actions.isTestingSkill ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Sparkles className="size-3.5" />
              )}
              <span>执行改写</span>
            </Button>

            {/* 📂 作战产物库直达 */}
            <Button
              size="sm"
              variant="ghost"
              className="h-6.5 px-2 text-[11px] font-medium text-amber-900/80 hover:text-amber-950 bg-white/70 hover:bg-white border border-amber-200/60 rounded-lg shadow-2xs transition-all flex items-center gap-1"
              onClick={onOpenArtifacts}
              title="查看当前简历的 AI 作战产物"
            >
              <FolderArchive className="size-3 text-amber-600" />
              <span className="hidden md:inline">产物库</span>
            </Button>
          </div>

          <div className="w-[1px] h-4 bg-border/50 mx-1.5" />

          <div className="flex items-center gap-0.5">
            <Button
              variant="ghost"
              size="sm"
              className="group h-8 px-2 hover:px-2.5 text-muted-foreground hover:bg-background hover:shadow-sm rounded-lg transition-all duration-300 ease-out flex items-center"
              onClick={() => setPreviewOpen(true)}
            >
              <Eye className="h-4 w-4 shrink-0 text-sky-500 group-hover:text-sky-600 transition-colors" />
              <span className="max-w-0 overflow-hidden opacity-0 group-hover:max-w-[100px] group-hover:opacity-100 group-hover:ml-1.5 text-[13px] font-medium whitespace-nowrap text-foreground transition-all duration-300 ease-out">
                预览 PDF
              </span>
            </Button>
            <PdfPreviewDialog previewOpen={previewOpen} setPreviewOpen={setPreviewOpen} avatarUrl={editingItem?.avatar_url} />

            {EXPORT_MENUS.map(menu => {
              const busy = menu.key === "images" ? actions.isGeneratingImages : actions.isGeneratingPdf
              const Icon = menu.icon
              return (
                <DropdownMenu key={menu.key}>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="group h-8 px-2 hover:px-2.5 text-muted-foreground hover:bg-background hover:shadow-sm rounded-lg transition-all duration-300 ease-out flex items-center"
                      disabled={busy}
                    >
                      {busy ? <RefreshCw className="h-4 w-4 shrink-0 animate-spin" /> : <Icon className={`h-4 w-4 shrink-0 transition-colors ${menu.triggerIconClass}`} />}
                      <span className="max-w-0 overflow-hidden opacity-0 group-hover:max-w-[100px] group-hover:opacity-100 group-hover:ml-1.5 text-[13px] font-medium whitespace-nowrap text-foreground transition-all duration-300 ease-out">
                        {busy ? menu.busyLabel : menu.label}
                      </span>
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-40 p-1 shadow-lg rounded-xl border-slate-200">
                    {menu.items.map(item => {
                      const ItemIcon = item.itemIcon
                      return (
                        <DropdownMenuItem
                          key={item.template}
                          className="flex items-center gap-2 py-1.5 px-2.5 cursor-pointer text-xs"
                          onClick={() => (menu.key === "images" ? actions.handleSaveImages(item.template) : actions.handleSavePdf(item.template))}
                        >
                          <ItemIcon className={`size-3.5 ${item.itemIconClass}`} />
                          <span>{item.label}</span>
                        </DropdownMenuItem>
                      )
                    })}
                  </DropdownMenuContent>
                </DropdownMenu>
              )
            })}
          </div>

          <div className="w-[1px] h-4 bg-border/50 mx-1.5" />

          <Button
            size="sm"
            className="group h-8 px-4 text-[13px] font-medium bg-zinc-900 text-zinc-50 hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200 rounded-lg shadow-sm transition-all ml-0.5 flex items-center"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? <Loader2 className="h-4 w-4 shrink-0 animate-spin" /> : <Save className="h-4 w-4 shrink-0" />}
            <span className="ml-1.5 whitespace-nowrap">{saving ? "保存中…" : "保存并同步"}</span>
          </Button>
        </div>
      </div>
    </header>
  )
}
