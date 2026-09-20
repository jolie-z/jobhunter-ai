"use client"

import { API_BASE } from "@/lib/api"
import React, { useState, useRef } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Upload,
  Loader2,
  FolderArchive,
  Github,
  ShieldCheck,
  ShieldAlert,
  CheckCircle,
} from "lucide-react"
import type { AuditReport } from "../skill-selector"


interface SkillUploadDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSuccess: (newSkillId?: string) => Promise<void>
}


// 与后端 409 覆盖确认配套的重发流程：首发 → 409 弹确认 → 同意带 force 重发。
// 取消返回 null（调用方提示"未做任何修改"）；纯函数便于单测三态。
export async function sendWithOverrideConfirm(
  doSend: (force: boolean) => Promise<Response>,
  confirmFn: (message: string) => boolean = (message) => window.confirm(message)
): Promise<Response | null> {
  let res = await doSend(false)
  if (res.status === 409) {
    const conflict = await res.json().catch(() => ({ detail: "已存在同名技能，是否替换覆盖？" }))
    if (!confirmFn(conflict.detail || "已存在同名技能，是否替换覆盖？")) {
      return null
    }
    res = await doSend(true)
  }
  return res
}

// 组件内局部状态类型（非导出）

export function SkillUploadDialog({
  open,
  onOpenChange,
  onSuccess,
}: SkillUploadDialogProps) {
  const [importTab, setImportTab] = useState<"local" | "github">("local")
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadFiles, setUploadFiles] = useState<FileList | null>(null)
  const [uploadName, setUploadName] = useState("")
  const [securityMode] = useState<"clean" | "strict">("clean")
  const [uploading, setUploading] = useState(false)

  const [githubUrl, setGithubUrl] = useState("")
  const [githubName, setGithubName] = useState("")
  const [githubImporting, setGithubImporting] = useState(false)

  const [auditReport, setAuditReport] = useState<AuditReport | null>(null)
  const [lastImportedSkill, setLastImportedSkill] = useState<string | null>(null)
  const [importSuccess, setImportSuccess] = useState(false)
  const [uploadSuccess, setUploadSuccess] = useState(false)

  const fileInputRef = useRef<HTMLInputElement>(null)

  const resetState = () => {
    setAuditReport(null)
    setUploadFile(null)
    setUploadFiles(null)
    setUploadName("")
    setGithubUrl("")
    setGithubName("")
    setUploadSuccess(false)
    setImportSuccess(false)
  }

  const handleUploadLocal = async () => {
    if (!uploadFile && (!uploadFiles || uploadFiles.length === 0)) return

    setUploading(true)
    setUploadSuccess(false)
    setAuditReport(null)
    try {
      const buildForm = (force: boolean) => {
        const formData = new FormData()
        formData.append("mode", securityMode)
        if (uploadName.trim()) {
          formData.append("name", uploadName.trim())
        }

        if (uploadFiles && uploadFiles.length > 1) {
          for (let i = 0; i < uploadFiles.length; i++) {
            formData.append("files", uploadFiles[i])
          }
        } else if (uploadFile) {
          formData.append("file", uploadFile)
          formData.append("name", uploadName.trim() || uploadFile.name.replace(/\.(md|zip)$/i, ""))
        }
        if (force) {
          formData.append("force", "true")
        }
        return formData
      }

      const doSend = async (force: boolean) => {
        let res = await fetch(`${API_BASE}/api/resume-editor/skills/upload`, {
          method: "POST",
          body: buildForm(force),
        })
        if (!res.ok && res.status === 404) {
          res = await fetch(`${API_BASE}/resume-editor/skills/upload`, {
            method: "POST",
            body: buildForm(force),
          })
        }
        return res
      }

      const res = await sendWithOverrideConfirm(doSend)
      if (!res) {
        alert("已取消，未做任何修改。")
        return
      }

      const data = await res.json()
      if (data.success) {
        setUploadSuccess(true)
        setAuditReport(data.audit_report)
        const finalName = data.skill?.name || uploadName.trim() || "新技能"
        setLastImportedSkill(finalName)
        await onSuccess(data.skill?.id)
        setTimeout(() => setUploadSuccess(false), 5000)
      } else {
        alert(`❌ 上传失败：${data.detail || data.error}`)
      }
    } catch (error) {
      alert(`❌ 网络请求失败：${error}`)
    } finally {
      setUploading(false)
    }
  }

  const handleImportGithub = async () => {
    if (!githubUrl.trim()) return

    setGithubImporting(true)
    setImportSuccess(false)
    setAuditReport(null)
    try {
      const doSend = async (force: boolean) => {
        let res = await fetch(`${API_BASE}/api/resume-editor/skills/import-github`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            repo_url: githubUrl.trim(),
            suggested_name: githubName.trim() || undefined,
            mode: securityMode,
            force,
          }),
        })
        if (!res.ok && res.status === 404) {
          res = await fetch(`${API_BASE}/resume-editor/skills/import-github`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              repo_url: githubUrl.trim(),
              suggested_name: githubName.trim() || undefined,
              mode: securityMode,
              force,
            }),
          })
        }
        return res
      }

      const res = await sendWithOverrideConfirm(doSend)
      if (!res) {
        alert("已取消，未做任何修改。")
        return
      }

      const data = await res.json()
      if (data.success) {
        setImportSuccess(true)
        setAuditReport(data.audit_report)
        const finalName = data.skill?.name || githubName.trim() || "GitHub 技能包"
        setLastImportedSkill(finalName)
        await onSuccess(data.skill?.id)
        setTimeout(() => setImportSuccess(false), 5000)
      } else {
        alert(`❌ GitHub 导入失败：${data.detail || data.error}`)
      }
    } catch (error) {
      alert(`❌ 网络错误：${error}`)
    } finally {
      setGithubImporting(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v)
        if (!v) resetState()
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <Upload className="size-4 text-indigo-600" />
            导入自定义 Skill 技能包
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground">
            支持直接导入 <code className="text-indigo-600 font-mono">.md</code>、<code className="text-indigo-600 font-mono">.zip</code> 压缩包、文件夹或一键同步 GitHub 开源技能库。
          </DialogDescription>
        </DialogHeader>

        {/* 切换 Tab */}
        <div className="flex items-center gap-2 border-b border-slate-100 pb-2">
          <button
            onClick={() => setImportTab("local")}
            className={`flex items-center gap-1.5 px-3 py-1 text-xs rounded-md font-medium transition-all ${
              importTab === "local"
                ? "bg-indigo-50 text-indigo-600 shadow-xs"
                : "text-slate-500 hover:text-slate-800"
            }`}
          >
            <FolderArchive className="size-3.5" />
            本地文件 / ZIP 压缩包
          </button>
          <button
            onClick={() => setImportTab("github")}
            className={`flex items-center gap-1.5 px-3 py-1 text-xs rounded-md font-medium transition-all ${
              importTab === "github"
                ? "bg-indigo-50 text-indigo-600 shadow-xs"
                : "text-slate-500 hover:text-slate-800"
            }`}
          >
            <Github className="size-3.5" />
            GitHub 仓库一键导入
          </button>
        </div>

        {/* 审计报告展示区 */}
        {auditReport && (
          <div className="rounded-md border border-emerald-200 bg-emerald-50/60 p-3 space-y-1.5 text-xs text-emerald-900">
            <div className="flex items-center gap-1.5 font-semibold text-emerald-700">
              <ShieldCheck className="size-4" />
              <span>已成功导入「{lastImportedSkill}」并完成安全扫描</span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-600 pt-1">
              <div>🎯 核心 SOP: <span className="font-mono text-emerald-700">{auditReport.main_entry}</span></div>
              <div>📚 References: <span className="font-semibold text-emerald-700">{auditReport.references_count || 0} 份资料</span></div>
            </div>
            {auditReport.ignored_scripts_count && auditReport.ignored_scripts_count > 0 ? (
              <div className="text-[11px] text-amber-700 flex items-start gap-1 pt-1 bg-amber-50/80 p-1.5 rounded">
                <ShieldAlert className="size-3.5 shrink-0 mt-0.5" />
                <span>已自动安全隔离 {auditReport.ignored_scripts_count} 个非文本脚本（如 {auditReport.ignored_scripts?.slice(0, 2).join(", ")}）</span>
              </div>
            ) : null}
          </div>
        )}

        {importTab === "local" ? (
          <div className="space-y-3 py-1">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-700">选择文件或压缩包</label>
              <div className="flex gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".md,.markdown,.zip,.json,.txt"
                  onChange={(e) => {
                    const f = e.target.files?.[0] || null
                    setUploadFile(f)
                    setUploadFiles(null)
                    if (f && !uploadName) {
                      setUploadName(f.name.replace(/\.(md|zip)$/i, ""))
                    }
                  }}
                  className="hidden"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="flex-1 h-9 text-xs border-dashed hover:border-indigo-400 hover:bg-indigo-50/40"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <FolderArchive className="size-3.5 mr-1.5 text-indigo-500" />
                  {uploadFile ? uploadFile.name : "选择 .md / .zip 文件"}
                </Button>
              </div>
              {uploadFile && (
                <p className="text-[11px] text-emerald-600 flex items-center gap-1 font-medium pt-1">
                  <CheckCircle className="size-3" />
                  已就绪: {uploadFile.name} ({(uploadFile.size / 1024).toFixed(1)} KB)
                </p>
              )}
            </div>

            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-700">技能显示名称（可选）</label>
              <Input
                placeholder="例如：LLM大模型算法求职改写"
                value={uploadName}
                onChange={(e) => {
                  setUploadName(e.target.value)
                  setUploadSuccess(false)
                }}
                className="text-xs h-8"
              />
            </div>
          </div>
        ) : (
          <div className="space-y-3 py-1">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-700">GitHub 开源仓库 URL</label>
              <Input
                placeholder="https://github.com/wanyichen06/LLMInternSkill"
                value={githubUrl}
                onChange={(e) => {
                  setGithubUrl(e.target.value)
                  setImportSuccess(false)
                }}
                className="text-xs h-8 font-mono"
              />
              <p className="text-[11px] text-muted-foreground">
                系统会自动拉取该仓库的最新代码包，自动定位 <code className="text-indigo-600 font-mono">SKILL.md</code> 并挂载 <code className="text-indigo-600 font-mono">references/</code>。
              </p>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-700">自定义技能命名（可选）</label>
              <Input
                placeholder="例如：大模型算法实习技能库"
                value={githubName}
                onChange={(e) => {
                  setGithubName(e.target.value)
                  setImportSuccess(false)
                }}
                className="text-xs h-8"
              />
            </div>
          </div>
        )}

        {/* 🛡️ 安全防御模式选择 */}
        <div className="rounded-md border border-slate-200 bg-slate-50/70 p-2.5 space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-700 flex items-center gap-1">
              <ShieldCheck className="size-3.5 text-indigo-500" />
              安全白名单防护策略
            </span>
            <span className="text-[11px] font-semibold text-indigo-600">纯净过滤模式 (推荐)</span>
          </div>
          <p className="text-[11px] text-slate-500">
            仅允许纯文本 Markdown/JSON 入库。若仓库中附带 Python/Shell 代码将自动物理隔离，免除手动清理负担。
          </p>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            variant="outline"
            size="sm"
            className="text-xs h-8"
            onClick={() => onOpenChange(false)}
            disabled={uploading || githubImporting}
          >
            关闭
          </Button>
          {importTab === "local" ? (
            uploadSuccess ? (
              <Button
                size="sm"
                disabled
                className="gap-1.5 text-xs h-8 bg-emerald-600 text-white font-medium shadow-sm transition-all"
              >
                <CheckCircle className="size-3.5" />
                ✓ 导入成功
              </Button>
            ) : (
              <Button
                size="sm"
                onClick={handleUploadLocal}
                disabled={(!uploadFile && (!uploadFiles || uploadFiles.length === 0)) || uploading}
                className="gap-1.5 text-xs h-8 bg-indigo-600 hover:bg-indigo-700 text-white"
              >
                {uploading ? (
                  <>
                    <Loader2 className="size-3.5 animate-spin" />
                    正在解压与安全扫描...
                  </>
                ) : (
                  <>
                    <Upload className="size-3.5" />
                    确认导入技能包
                  </>
                )}
              </Button>
            )
          ) : importSuccess ? (
            <Button
              size="sm"
              disabled
              className="gap-1.5 text-xs h-8 bg-emerald-600 text-white font-medium shadow-sm transition-all"
            >
              <CheckCircle className="size-3.5" />
              ✓ 安装成功
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={handleImportGithub}
              disabled={!githubUrl.trim() || githubImporting}
              className="gap-1.5 text-xs h-8 bg-indigo-600 hover:bg-indigo-700 text-white"
            >
              {githubImporting ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" />
                  正在拉取并解析仓库...
                </>
              ) : (
                <>
                  <Github className="size-3.5" />
                  一键拉取并安装
                </>
              )}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
