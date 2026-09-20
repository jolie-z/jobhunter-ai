"use client"

import { useState, useEffect, useRef } from "react"
import { Input } from "@/components/ui/input"
import { API_BASE } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Plus, ShieldCheck, X, UserCircle2, ChevronDown, Loader2 } from "lucide-react"
import { useOptionalStrategyStore } from "@/hooks/use-strategy-store"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

interface Field {
  id: string
  label: string
  value: string
  placeholder?: string
}

const STANDARD_FIELD_DEFS: Array<{
  key: string
  label: string
  id: string
  placeholder?: string
}> = [
  { key: "name", label: "姓名", id: "std_name", placeholder: "请输入姓名" },
  { key: "title", label: "求职意向", id: "std_title", placeholder: "如：前端开发工程师" },
  { key: "phone", label: "手机", id: "std_phone", placeholder: "请输入手机号" },
  { key: "email", label: "邮箱", id: "std_email", placeholder: "请输入邮箱" },
  { key: "location", label: "所在城市", id: "std_location", placeholder: "请输入城市" },
  { key: "website", label: "个人主页", id: "std_website", placeholder: "如：github.com/xxx" },
]

let customFieldSeq = 1000
function genCustomFieldId(prefix = "custom") {
  return `${prefix}_${Date.now()}_${++customFieldSeq}`
}

function parseJsonToFields(info: Record<string, any>, prevFields: Field[] = []): Field[] {
  const f: Field[] = []
  const prevMap = new Map(prevFields.map(field => [field.label, field.id]))

  // 1. 标准字段使用确定且恒定的静态 ID，保障 React Key 绝对稳定，输入框绝不丢失焦点
  for (const def of STANDARD_FIELD_DEFS) {
    if (info[def.key] !== undefined) {
      f.push({
        id: def.id,
        label: def.label,
        value: info[def.key] || "",
        placeholder: def.placeholder,
      })
    }
  }

  // 2. 自定义字段（优先复用已有 ID，避免外部刷新时重置 Key）
  const standardKeys = ["name", "title", "phone", "email", "location", "website", "avatar_url"]
  for (const [k, v] of Object.entries(info)) {
    if (!standardKeys.includes(k) && v !== null && v !== undefined && typeof v !== "object") {
      const stableId = prevMap.get(k) || genCustomFieldId(`custom_${k}`)
      f.push({
        id: stableId,
        label: k,
        value: String(v),
      })
    }
  }

  if (f.length === 0) {
    return [
      { id: "std_name", label: "姓名", value: "", placeholder: "请输入姓名" },
      { id: "std_title", label: "求职意向", value: "", placeholder: "如：前端开发工程师" },
      { id: "std_phone", label: "手机", value: "", placeholder: "请输入手机号" },
      { id: "std_email", label: "邮箱", value: "", placeholder: "请输入邮箱" },
    ]
  }
  return f
}

export function PersonalInfo() {
  const strategyStore = useOptionalStrategyStore()
  const editingItem = strategyStore?.editingItem
  const fetchConfig = strategyStore?.fetchConfig
  // 头像编辑权归属：仅「配置大盘-简历库」页面（StrategyContext 存在）可上传/更换/删除；
  // 岗位工作区编辑区一律只读——只自动拉取启用底稿的照片，hover 引导用户前往简历库修改。
  const canEditAvatar = Boolean(strategyStore)
  const { resumeData, updatePersonalInfo } = useResumeV2Store()
  const [fields, setFields] = useState<Field[]>([])
  const prevJsonStrRef = useRef<string>("")
  const isInternalChangeRef = useRef<boolean>(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [avatarDataUrl, setAvatarDataUrl] = useState<string>("")

  useEffect(() => {
    const fetchAndSetAvatar = (url: string) => {
      // Sync URL to store so print/export can use it
      if (resumeData?.personalInfo?.avatar_url !== url) {
        updatePersonalInfo({ avatar_url: url })
      }
      const cacheKey = `avatar_${url}`
      const cached = localStorage.getItem(cacheKey)
      if (cached) {
        setAvatarDataUrl(cached)
        return
      }
      fetch(url)
        .then(res => res.blob())
        .then(blob => {
          const reader = new FileReader()
          reader.onloadend = () => {
            const base64 = reader.result as string
            setAvatarDataUrl(base64)
            try {
              localStorage.setItem(cacheKey, base64)
            } catch (e) {
              // Ignore storage quota limits
            }
          }
          reader.readAsDataURL(blob)
        })
        .catch(() => {
          setAvatarDataUrl(url)
        })
    }

    const effectiveAvatar = resumeData?.personalInfo?.avatar_url || editingItem?.avatar_url
    if (effectiveAvatar) {
      fetchAndSetAvatar(effectiveAvatar)
      return
    }

    // 自动读取“飞书-我的简历库-当前状态=启用”的照片字段
    const fetchActiveAvatar = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/strategy/config`)
        const data = await res.json()
        if (data.status === "success" && Array.isArray(data.resumes)) {
          const activeResume = data.resumes.find((r: any) => r.status === "启用" || r.status === "Active")
          if (activeResume && activeResume.avatar_url) {
            fetchAndSetAvatar(activeResume.avatar_url)
            return
          }
        }
      } catch (e) {
        console.error("Failed to fetch active resume avatar:", e)
      }
      setAvatarDataUrl("")
    }
    fetchActiveAvatar()
  }, [editingItem?.avatar_url, resumeData?.personalInfo?.avatar_url])

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    // 本地草稿在飞书无对应记录，后端会拒绝；提前给出明确提示，不做静默 no-op
    if (!editingItem?.record_id) {
      alert("该简历尚未保存同步（本地草稿），请先点击右上角「保存并同步」再上传照片")
      if (fileInputRef.current) fileInputRef.current.value = ""
      return
    }
    const MAX_AVATAR_SIZE = 5 * 1024 * 1024
    if (file.size > MAX_AVATAR_SIZE) {
      alert(`❌ 图片过大（${(file.size / 1024 / 1024).toFixed(1)}MB），最大支持 5MB`)
      if (fileInputRef.current) fileInputRef.current.value = ""
      return
    }
    
    setIsUploading(true)
    const formData = new FormData()
    formData.append("file", file)
    formData.append("record_id", editingItem.record_id)

    try {
        const res = await fetch(`${API_BASE}/api/strategy/upload_avatar`, { method: "POST", body: formData })
        const data = await res.json()
        if (data.status === "success") {
            // refresh data to fetch the newly returned temp image URL
            if (fetchConfig) await fetchConfig(editingItem.record_id)
        } else {
            alert("❌ 上传失败: " + (data.detail || data.message || "未知错误"))
        }
    } catch (err) {
      alert("❌ 网络异常，照片上传失败")
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ""
    }
  }

  const hasAvatar = Boolean(avatarDataUrl || resumeData?.personalInfo?.avatar_url || editingItem?.avatar_url)
  const avatarVisual = isUploading ? (
    <Loader2 className="size-8 text-indigo-400 animate-spin" />
  ) : hasAvatar ? (
    <img src={avatarDataUrl || resumeData?.personalInfo?.avatar_url || editingItem?.avatar_url} alt="Avatar" className="h-full w-full object-cover" />
  ) : (
    <UserCircle2 className="size-10 text-indigo-200 sm:size-12" />
  )
  const avatarBoxClass = "flex h-28 w-20 shrink-0 items-center justify-center rounded-md border-2 border-indigo-100 bg-white shadow-sm sm:h-32 sm:w-24 overflow-hidden"

  useEffect(() => {
    // 🚀 如果是当前表单输入框内用户打字触发的 store 变更，直接拦截，绝不重置 fields，彻底杜绝跳焦/失焦
    if (isInternalChangeRef.current) {
      isInternalChangeRef.current = false
      return
    }

    const currentJsonStr = JSON.stringify(resumeData?.personalInfo || {})
    if (currentJsonStr !== prevJsonStrRef.current) {
      setFields((prev) => parseJsonToFields(resumeData?.personalInfo || {}, prev))
      prevJsonStrRef.current = currentJsonStr
    }
  }, [resumeData?.personalInfo])

  const notifyChange = (newFields: Field[]) => {
    setFields(newFields)
    
    const mapped: any = {}
    newFields.forEach(f => {
      const label = (f.label || "").trim()
      if (!label) return
      if (label === "姓名") mapped.name = f.value
      else if (label === "求职意向") mapped.title = f.value
      else if (label === "手机") mapped.phone = f.value
      else if (label === "邮箱") mapped.email = f.value
      else if (label === "所在城市") mapped.location = f.value
      else if (label === "个人主页" || label === "个人主页/GitHub") mapped.website = f.value
      else mapped[label] = f.value
    })

    // 修复：找出旧状态中存在，但在新表单中已经被删除/重命名的 key
    // 将它们赋值为 undefined，这样 updatePersonalInfo (Zustand 浅合并) 就能把旧 key 抹除，防止键爆炸
    // avatar_url 例外：它由照片上传/删除逻辑管理，不归表单管，这里不能抹
    if (resumeData?.personalInfo) {
      Object.keys(resumeData.personalInfo).forEach(key => {
        if (key === "avatar_url") return
        if (!(key in mapped)) {
          mapped[key] = undefined
        }
      })
    }

    // 保留已有的照片头像地址
    if (resumeData?.personalInfo?.avatar_url) {
      mapped.avatar_url = resumeData.personalInfo.avatar_url
    }

    // 标记内部输入，阻断循环重绘
    isInternalChangeRef.current = true
    const newJsonStr = JSON.stringify(mapped)
    prevJsonStrRef.current = newJsonStr
    updatePersonalInfo(mapped)
  }

  const updateField = (id: string, patch: Partial<Field>) =>
    notifyChange(fields.map((f) => (f.id === id ? { ...f, ...patch } : f)))

  const removeField = (id: string) => notifyChange(fields.filter((f) => f.id !== id))

  const addSpecificField = (label: string, placeholder: string) =>
    notifyChange([...fields, { id: genCustomFieldId(label), label, value: "", placeholder }])

  const addCustomField = () =>
    notifyChange([...fields, { id: genCustomFieldId("custom"), label: "自定义", value: "", placeholder: "请输入内容" }])

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-1.5 rounded-md bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
        <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
        <span className="text-pretty">注意：个人信息不会传给大模型，仅用于后续简历拼接使用</span>
      </div>

      <div className="flex flex-col sm:flex-row gap-6 items-start">
        {/* 左侧头像区：简历库页可编辑（hover 遮罩+点击上传）；岗位工作区只读（hover 出 Tooltip 引导） */}
        <div className="relative group/avatar mt-1">
        {canEditAvatar ? (
          <div
            className={`group relative cursor-pointer transition-all hover:shadow-md ${avatarBoxClass}`}
            onClick={() => !isUploading && fileInputRef.current?.click()}
          >
            {avatarVisual}
            <div className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 transition-opacity group-hover:opacity-100">
              <span className="text-[10px] font-medium text-white">{hasAvatar ? "更换照片" : "上传照片"}</span>
            </div>
            <input
              type="file"
              ref={fileInputRef}
              className="hidden"
              accept="image/*"
              onChange={handleUpload}
            />
          </div>
        ) : (
          <Tooltip>
            <TooltipTrigger asChild>
              <div role="img" tabIndex={0} aria-label="照片（只读）" className={`cursor-default ${avatarBoxClass}`}>
                {avatarVisual}
              </div>
            </TooltipTrigger>
            <TooltipContent side="right">请前往 配置大盘-简历库 修改照片</TooltipContent>
          </Tooltip>
        )}
        {canEditAvatar && hasAvatar && !isUploading && (
          <Button
            size="icon"
            variant="destructive"
            className="absolute -top-2 -right-2 size-6 rounded-full opacity-0 shadow-sm transition-opacity group-hover/avatar:opacity-100 z-10"
            onClick={(e) => {
              e.stopPropagation();
              setAvatarDataUrl("");
              updatePersonalInfo({ avatar_url: null });
            }}
          >
            <X className="size-3" />
          </Button>
        )}
      </div>

        {/* 右侧字段表单区 */}
        <div className="flex-1 w-full">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {fields.map((field) => (
              <div key={field.id} className="group flex items-center gap-1.5">
                <Input
                  value={field.label || ""}
                  onChange={(e) => updateField(field.id, { label: e.target.value })}
                  className="h-9 w-24 shrink-0 border-dashed text-sm font-medium text-muted-foreground"
                  aria-label="字段名称"
                />
                <Input
                  value={field.value || ""}
                  placeholder={field.placeholder || "请输入"}
                  onChange={(e) => updateField(field.id, { value: e.target.value })}
                  className="h-9 flex-1"
                  aria-label="字段内容"
                />
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-9 w-9 shrink-0 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                  onClick={() => removeField(field.id)}
                >
                  <X className="h-4 w-4" />
                  <span className="sr-only">删除字段</span>
                </Button>
              </div>
            ))}
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" className="bg-transparent border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600">
                  <Plus className="mr-1.5 h-4 w-4" />
                  快捷添加
                  <ChevronDown className="ml-1 h-3 w-3 opacity-50" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-48">
                <DropdownMenuItem onClick={() => addSpecificField("年龄", "如：1998.05")}>
                  年龄/出生年月
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => addSpecificField("个人主页", "如：github.com/xxx")}>
                  个人主页/GitHub
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => addSpecificField("微信", "请输入微信号")}>
                  微信
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => addSpecificField("到岗时间", "如：随时到岗")}>
                  到岗时间
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            <Button variant="ghost" size="sm" className="text-muted-foreground hover:text-foreground" onClick={addCustomField}>
              <Plus className="mr-1.5 h-4 w-4" />
              新增自定义字段
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
