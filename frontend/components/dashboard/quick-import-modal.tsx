"use client"

import { API_BASE } from "@/lib/api"
import { fetchMissingKeys } from "@/lib/readiness"
import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  ImageIcon,
  UploadCloud,
  X,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { ConfigGateDialog } from "@/components/dashboard/config-gate-dialog"


// 与后端 service._PLACEHOLDER_VALUES 对齐：命中即视为该字段没拿到
const PLACEHOLDER_VALUES = new Set(["", "-", "未知", "无", "未解析出岗位名", "未知猎头/公司"])

// 与 backend/app/session/registry.py 的注册表规范名保持一致
const PLATFORM_OPTIONS = ["BOSS直聘", "智联招聘", "前程无忧", "猎聘", "小红书", "未知"]

const HARD_KEYS = ["公司名称", "岗位名称", "岗位详情"] as const
const SOFT_LABELS: Record<string, string> = { 薪资: "薪资", 城市: "城市", 经验要求: "经验", 学历要求: "学历" }

type FieldMap = Record<string, string>

type DuplicateInfo = { record_id: string; 公司名称: string; 岗位名称: string; 跟进状态: string; review_url?: string }
type ImportWarnings = { hard_missing: string[]; soft_missing: string[]; link_missing: boolean; duplicate: DuplicateInfo | null }
const EMPTY_WARNINGS: ImportWarnings = { hard_missing: [], soft_missing: [], link_missing: false, duplicate: null }

const TEXT_FIELDS: { key: string; label: string; required?: boolean }[] = [
  { key: "公司名称", label: "公司名称", required: true },
  { key: "岗位名称", label: "岗位名称", required: true },
  { key: "薪资", label: "薪资" }, { key: "城市", label: "城市" },
  { key: "经验要求", label: "经验要求" }, { key: "学历要求", label: "学历要求" },
  { key: "公司规模", label: "公司规模" }, { key: "所属行业", label: "所属行业" },
  { key: "工作地址", label: "工作地址" }, { key: "发布日期", label: "发布日期" },
]

const isMeaningful = (v: string | undefined) => !PLACEHOLDER_VALUES.has((v ?? "").trim())

const BOSS_MOBILE_URL_REGEX = /(?:m\.zhipin\.com\/(?:mpa\/html\/weijd(?:\/weijd-job)?|job_detail)|www\.zhipin\.com\/mpa\/html\/weijd(?:\/weijd-job)?)\/([0-9a-zA-Z~_-]+)/
const JOB51_MOBILE_URL_REGEX = /(?:msearch\.51job\.com|m\.51job\.com)\/jobs\/(?:([a-zA-Z0-9_-]+)\/)?(\d+)\.html/

export function normalizeJobUrl(url: string): { normalized: string; isConverted: boolean; platform?: string } {
  const trimmed = url.trim()
  if (!trimmed) return { normalized: trimmed, isConverted: false }
  const matchBoss = trimmed.match(BOSS_MOBILE_URL_REGEX)
  if (matchBoss && matchBoss[1]) {
    return {
      normalized: `https://www.zhipin.com/job_detail/${matchBoss[1]}.html`,
      isConverted: true,
      platform: "BOSS直聘",
    }
  }
  const match51 = trimmed.match(JOB51_MOBILE_URL_REGEX)
  if (match51 && match51[2]) {
    const city = match51[1] || "all"
    return {
      normalized: `https://jobs.51job.com/${city}/${match51[2]}.html`,
      isConverted: true,
      platform: "前程无忧",
    }
  }
  return { normalized: trimmed, isConverted: false }
}

// 解析返回可能带数值型字段，统一转字符串并剔除落库时才生成的键
function normalizeFields(raw: Record<string, unknown>): { fields: FieldMap; isConverted: boolean } {
  const out: FieldMap = {}
  let isConverted = false
  for (const key of Object.keys(raw)) {
    if (["跟进状态", "抓取时间", "record_id"].includes(key)) continue
    let val = String(raw[key] ?? "")
    if (key === "岗位链接" && val) {
      const conv = normalizeJobUrl(val)
      val = conv.normalized
      if (conv.isConverted) isConverted = true
    }
    out[key] = val
  }
  return { fields: out, isConverted }
}

type Props = {
  onClose: () => void
  /** 录入成功后回调（静默刷新岗位列表） */
  onSuccess: () => void
}

export function QuickImportModal({ onClose, onSuccess }: Props) {
  const router = useRouter()
  const [step, setStep] = useState<"input" | "confirm" | "done">("input")
  const [importText, setImportText] = useState("")
  const [importImages, setImportImages] = useState<string[]>([])
  const [parsing, setParsing] = useState(false)
  const [parseError, setParseError] = useState("")
  // 视觉模型就绪度（打开弹窗时预检；拉取失败时置 null = 不预拦，由后端 400 兜底）
  const [visionMissing, setVisionMissing] = useState<string[] | null>(null)
  const [gateOpen, setGateOpen] = useState(false)
  const [fields, setFields] = useState<FieldMap>({})
  const [warnings, setWarnings] = useState<ImportWarnings>(EMPTY_WARNINGS)
  const [forceDuplicate, setForceDuplicate] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [confirmError, setConfirmError] = useState("")
  const [summary, setSummary] = useState("")
  const [reviewUrl, setReviewUrl] = useState("")
  const [linkConvertedNotice, setLinkConvertedNotice] = useState(false)

  // 弹窗打开时预检视觉模型就绪度（极速录入截图识别依赖视觉模型；预检失败保持 null 不拦截）
  useEffect(() => {
    let cancelled = false
    fetchMissingKeys("vision").then((missing) => {
      if (!cancelled) setVisionMissing(missing)
    })
    return () => { cancelled = true }
  }, [])

  // 将文件转为 Base64
  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    if (files.length === 0) return
    files.forEach(file => {
      const reader = new FileReader()
      reader.readAsDataURL(file)
      reader.onload = () => {
        setImportImages(prev => [...prev, reader.result as string])
      }
    })
    e.target.value = "" // 允许重复上传相同图片
  }

  const handleRemoveImage = (indexToRemove: number) => {
    setImportImages(prev => prev.filter((_, index) => index !== indexToRemove))
  }

  // 监听剪贴板粘贴：图片直接进截图区，不当作文字粘进文本框
  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items
    if (!items) return
    let hasImage = false
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.indexOf("image") !== -1) {
        hasImage = true
        const file = items[i].getAsFile()
        if (!file) continue
        const reader = new FileReader()
        reader.readAsDataURL(file)
        reader.onload = () => {
          setImportImages(prev => [...prev, reader.result as string])
        }
      }
    }
    if (hasImage) {
      e.preventDefault()
    }
  }

  // 第一步：解析（图文一起传，后端视觉打底、文本覆盖合并；只解析不落库）
  // imagesOverride：闸门「仅文本解析」次选动作清空截图后自动续跑时使用
  const handleParse = async (imagesOverride?: string[]) => {
    const imgs = imagesOverride ?? importImages
    if (!importText.trim() && imgs.length === 0) {
      setParseError("请粘贴文本或上传至少一张截图！")
      return
    }
    // 视觉闸门：带截图但视觉模型未配置 → 拦截并引导配置（预检失败时由后端 400 兜底）
    if (imgs.length > 0 && visionMissing !== null && visionMissing.length > 0) {
      setGateOpen(true)
      return
    }
    setParsing(true)
    setParseError("")
    try {
      const response = await fetch(`${API_BASE}/api/jobs/import/parse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw_text: importText, images_base64: imgs }),
      })
      const result = await response.json()
      if (!response.ok) {
        if (result.detail?.code === "vision_not_configured") {
          setVisionMissing(result.detail.missing || ["VISION_MODEL"])
          setGateOpen(true)
          return
        }
        setParseError(typeof result.detail === "string" ? result.detail : "解析失败，请重试")
        return
      }
      const { fields: normalizedFields, isConverted } = normalizeFields(result.fields ?? {})
      setFields(normalizedFields)
      setLinkConvertedNotice(isConverted)
      setWarnings({ ...EMPTY_WARNINGS, ...(result.warnings ?? {}) })
      setForceDuplicate(false)
      setStep("confirm")
    } catch {
      setParseError("网络请求失败，请检查后端服务")
    } finally {
      setParsing(false)
    }
  }

  // 第二步：确认落库（服务端二次校验 + 查重兜底）
  const handleConfirm = async () => {
    setConfirming(true)
    setConfirmError("")
    try {
      const response = await fetch(`${API_BASE}/api/jobs/import/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields, force_duplicate: forceDuplicate }),
      })
      const result = await response.json()
      if (!response.ok) {
        const detail = result.detail
        if (response.status === 409 && detail?.existing) {
          setWarnings(prev => ({ ...prev, duplicate: detail.existing }))
        }
        setConfirmError(
          typeof detail === "string"
            ? detail
            : detail?.message
              ? detail.missing
                ? `${detail.message}（${detail.missing.join("、")}）`
                : detail.message
              : "录入失败，请重试",
        )
        return
      }
      setSummary(result.summary || "")
      setReviewUrl(result.review_url || "")
      onSuccess()
      setStep("done")
    } catch {
      setConfirmError("网络请求失败，请检查后端服务")
    } finally {
      setConfirming(false)
    }
  }

  const setField = (key: string, value: string) => {
    setFields(prev => ({ ...prev, [key]: value }))
  }

  const handleLinkChange = (value: string) => {
    const { normalized, isConverted, platform } = normalizeJobUrl(value)
    setLinkConvertedNotice(isConverted)
    setFields(prev => {
      const next: FieldMap = { ...prev, "岗位链接": normalized }
      if (platform && (!next["招聘平台"] || next["招聘平台"] === "未知")) {
        next["招聘平台"] = platform
      }
      return next
    })
  }

  // 随编辑实时重算缺失（用户可直接在表单里补全硬缺失字段）
  const hardMissing = HARD_KEYS.filter(key => !isMeaningful(fields[key]))
  const softMissing = Object.keys(SOFT_LABELS).filter(key => !isMeaningful(fields[key]))
  const linkMissing = !isMeaningful(fields["岗位链接"])
  const confirmBlocked = hardMissing.length > 0 || (Boolean(warnings.duplicate) && !forceDuplicate)

  const resetForNext = () => {
    setImportText("")
    setImportImages([])
    setFields({})
    setWarnings(EMPTY_WARNINGS)
    setForceDuplicate(false)
    setLinkConvertedNotice(false)
    setParseError("")
    setConfirmError("")
    setSummary("")
    setReviewUrl("")
    setStep("input")
  }

  const inputCls = (missing?: boolean) =>
    `w-full px-3 py-2 text-sm border rounded-lg outline-none focus:ring-2 bg-white ${
      missing ? "border-red-300 bg-red-50/40 focus:ring-red-200" : "border-gray-200 focus:ring-primary"
    }`

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="w-[640px] bg-white rounded-2xl shadow-2xl p-6 flex flex-col gap-4 max-h-[90vh] overflow-hidden">
        <div className="flex justify-between items-center shrink-0">
          <h3 className="text-lg font-bold text-gray-800">➕ 全渠道极速录入</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 p-1">
            <X size={20} />
          </button>
        </div>

        {/* ==================== Step 1：粘贴/上传 ==================== */}
        {step === "input" && (
          <>
            <div className="flex-1 overflow-y-auto pr-2 space-y-4">
              <p className="text-xs text-muted-foreground bg-blue-50/50 p-2.5 rounded border border-blue-100/50">
                💡 你可以粘贴文字，或上传多张招聘截图，也可图文一起提供。AI 解析后会先进入确认页，可补全岗位链接等缺失字段，确认后才写入飞书。
              </p>

              <textarea
                value={importText}
                onChange={(e) => setImportText(e.target.value)}
                onPaste={handlePaste}
                placeholder="在此粘贴文本，或直接 Cmd+V / Ctrl+V 粘贴截图..."
                className="h-32 w-full p-4 border border-border rounded-xl focus:ring-2 focus:ring-primary outline-none resize-none text-sm bg-gray-50/50"
              />

              <div className="flex flex-col gap-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-bold text-gray-700 flex items-center gap-1.5">
                    <ImageIcon size={16} /> 招聘截图 ({importImages.length})
                  </span>
                  <label className="cursor-pointer text-xs flex items-center gap-1.5 px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-md transition-colors">
                    <UploadCloud size={14} /> 上传图片
                    <input type="file" multiple accept="image/*" className="hidden" onChange={handleImageUpload} />
                  </label>
                </div>

                {importImages.length > 0 && (
                  <div className="flex gap-3 overflow-x-auto pb-2 custom-scrollbar">
                    {importImages.map((imgBase64, idx) => (
                      <div key={idx} className="relative group shrink-0 w-24 h-32 rounded-lg border border-gray-200 overflow-hidden bg-gray-50">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={imgBase64} alt={`upload-${idx}`} className="w-full h-full object-cover" />
                        <button
                          onClick={() => handleRemoveImage(idx)}
                          className="absolute top-1 right-1 bg-red-500/80 text-white rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-600"
                        >
                          <X size={12} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {parseError && (
                <div className="flex items-center gap-1.5 text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg p-2.5">
                  <AlertTriangle size={14} /> {parseError}
                </div>
              )}
            </div>

            <div className="flex justify-end gap-3 shrink-0 pt-2 border-t border-gray-100 mt-2">
              <Button variant="ghost" onClick={onClose}>取消</Button>
              <Button onClick={() => handleParse()} disabled={parsing} className="gap-2">
                {parsing ? <Spinner className="size-4" /> : null}
                {parsing ? "解析中..." : "开始解析"}
              </Button>
            </div>
          </>
        )}

        {/* ==================== Step 2：确认补全 ==================== */}
        {step === "confirm" && (
          <>
            <div className="flex-1 overflow-y-auto pr-2 space-y-3">
              {warnings.duplicate && (
                <div className="text-xs bg-amber-50 border border-amber-200 text-amber-800 rounded-lg p-3 space-y-2">
                  <div className="flex items-center gap-1.5 font-bold">
                    <AlertTriangle size={14} /> 疑似与已有岗位重复
                  </div>
                  <div>
                    已有记录：{warnings.duplicate.公司名称} - {warnings.duplicate.岗位名称}
                    （跟进状态：{warnings.duplicate.跟进状态 || "未知"}）
                    {warnings.duplicate.review_url && (
                      <a href={warnings.duplicate.review_url} target="_blank" rel="noreferrer" className="underline ml-1 inline-flex items-center gap-0.5">
                        查看 <ExternalLink size={10} />
                      </a>
                    )}
                  </div>
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={forceDuplicate}
                      onChange={(e) => setForceDuplicate(e.target.checked)}
                      className="accent-amber-600"
                    />
                    确认不是重复岗位，仍要录入
                  </label>
                </div>
              )}

              {hardMissing.length > 0 && (
                <div className="text-xs bg-red-50 border border-red-200 text-red-700 rounded-lg p-2.5">
                  ⛔ 必须提供：{hardMissing.join("、")} 还没有值。可直接在下方补全，或返回上一步补充 JD 文字 / 更换截图。
                </div>
              )}

              {softMissing.length > 0 && (
                <div className="text-xs text-gray-500 bg-gray-50 border border-gray-200 rounded-lg p-2.5">
                  未提供：{softMissing.map(key => SOFT_LABELS[key]).join("、")}（缺失会降低 AI 评级区分度，建议补全）
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                {TEXT_FIELDS.map(({ key, label, required }) => (
                  <label key={key} className="flex flex-col gap-1">
                    <span className="text-xs font-medium text-gray-600">
                      {label}
                      {required && <span className="text-red-500 ml-0.5">*</span>}
                    </span>
                    <input
                      value={fields[key] ?? ""}
                      onChange={(e) => setField(key, e.target.value)}
                      className={inputCls(required && !isMeaningful(fields[key]))}
                    />
                  </label>
                ))}

                <label className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-gray-600">招聘平台</span>
                  <select
                    value={fields["招聘平台"] ?? "未知"}
                    onChange={(e) => setField("招聘平台", e.target.value)}
                    className={inputCls()}
                  >
                    {PLATFORM_OPTIONS.map(p => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                    {!PLATFORM_OPTIONS.includes(fields["招聘平台"] ?? "") && (fields["招聘平台"] ?? "") !== "" && (
                      <option value={fields["招聘平台"]}>{fields["招聘平台"]}</option>
                    )}
                  </select>
                </label>

                <label className="flex flex-col gap-1">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-gray-600">岗位链接</span>
                    {linkConvertedNotice && (
                      <span className="text-[11px] text-emerald-600 font-medium">
                        ✓ 已转为电脑端链接
                      </span>
                    )}
                  </div>
                  <input
                    value={fields["岗位链接"] ?? ""}
                    onChange={(e) => handleLinkChange(e.target.value)}
                    placeholder="https://..."
                    className={linkMissing ? inputCls() + " border-amber-300 bg-amber-50/40 focus:ring-amber-200" : inputCls()}
                  />
                </label>
              </div>

              {linkMissing && (
                <div className="text-xs text-amber-700 bg-amber-50/60 border border-amber-200 rounded-lg p-2.5">
                  🔗 截图无法提取岗位链接；补上后该岗位才能自动投递。可留空，录入后仍可补录。
                </div>
              )}

              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-gray-600">
                  岗位详情<span className="text-red-500 ml-0.5">*</span>
                </span>
                <textarea
                  value={fields["岗位详情"] ?? ""}
                  onChange={(e) => setField("岗位详情", e.target.value)}
                  rows={5}
                  className={inputCls(!isMeaningful(fields["岗位详情"])) + " resize-y leading-relaxed"}
                />
              </label>

              {confirmError && (
                <div className="flex items-center gap-1.5 text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg p-2.5">
                  <AlertTriangle size={14} /> {confirmError}
                </div>
              )}
            </div>

            <div className="flex justify-end gap-3 shrink-0 pt-2 border-t border-gray-100 mt-2">
              <Button variant="ghost" onClick={() => setStep("input")}>返回修改</Button>
              <Button onClick={handleConfirm} disabled={confirming || confirmBlocked} className="gap-2">
                {confirming ? <Spinner className="size-4" /> : null}
                {confirming ? "录入中..." : "确认录入飞书"}
              </Button>
            </div>
          </>
        )}

        {/* ==================== Step 3：完成回执 ==================== */}
        {step === "done" && (
          <>
            <div className="flex-1 overflow-y-auto pr-2 space-y-3">
              <div className="flex items-center gap-2 text-green-600 font-bold text-sm">
                <CheckCircle2 size={18} /> 已录入飞书岗位总表
              </div>
              {summary && (
                <pre className="text-xs text-gray-700 bg-gray-50 rounded-lg p-3 whitespace-pre-wrap font-sans leading-relaxed">{summary}</pre>
              )}
              {!isMeaningful(fields["岗位链接"]) && (
                <div className="text-xs text-amber-700 bg-amber-50/60 border border-amber-200 rounded-lg p-2.5">
                  ⚠️ 该岗位暂未填链接，自动投递功能无法使用；可稍后在岗位详情或多维表格中补录。
                </div>
              )}
              {reviewUrl && (
                <a
                  href={reviewUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700 hover:underline"
                >
                  👉 在飞书多维表格中复核字段 <ExternalLink size={12} />
                </a>
              )}
            </div>

            <div className="flex justify-end gap-3 shrink-0 pt-2 border-t border-gray-100 mt-2">
              <Button variant="ghost" onClick={onClose}>关闭</Button>
              <Button onClick={resetForNext}>继续录入下一条</Button>
            </div>
          </>
        )}
      </div>

      {/* 视觉模型未配置闸门：截图识别不可用，引导前往配置 */}
      <ConfigGateDialog
        open={gateOpen}
        onClose={() => setGateOpen(false)}
        title="截图识别暂不可用"
        description="识别招聘截图需要「视觉模型」，当前还未配置。前往 配置大盘 → 系统底层配置 → LLM 大模型，填写「视觉模型」后即可使用。"
        missing={visionMissing ?? ["VISION_MODEL"]}
        onGoConfigure={() => router.push("/strategy?section=system")}
        secondaryLabel={importText.trim() ? "不用图片，仅按文本解析" : undefined}
        onSecondary={
          importText.trim()
            ? () => { setImportImages([]); setVisionMissing([]); handleParse([]) }
            : undefined
        }
      />
    </div>
  )
}
