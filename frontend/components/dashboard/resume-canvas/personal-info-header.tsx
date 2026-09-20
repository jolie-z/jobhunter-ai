import { useState } from "react"
import { Plus, X, UserCircle2, Phone, Mail, Link as LinkIcon, MessageCircle, MapPin, Briefcase } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import type { PersonalInfo, PersonalInfoField } from "@/lib/personal-info-parser"
import { cn } from "@/lib/utils"

interface PersonalInfoHeaderProps {
  info: PersonalInfo
  onChange: (info: PersonalInfo) => void
  isRaw?: boolean
}

// 自动根据字段标签分配一个适合的图标
function getFieldIcon(label: string) {
  const l = label.toLowerCase()
  if (l.includes("电话") || l.includes("手机") || l.includes("phone")) return <Phone className="size-3.5" />
  if (l.includes("邮箱") || l.includes("email")) return <Mail className="size-3.5" />
  if (l.includes("微信") || l.includes("wechat")) return <MessageCircle className="size-3.5" />
  if (l.includes("主页") || l.includes("网站") || l.includes("github") || l.includes("blog")) return <LinkIcon className="size-3.5" />
  if (l.includes("城市") || l.includes("地址") || l.includes("居") || l.includes("location")) return <MapPin className="size-3.5" />
  if (l.includes("年限") || l.includes("经验") || l.includes("经验")) return <Briefcase className="size-3.5" />
  return <div className="size-1.5 rounded-full bg-slate-300" /> // 默认小圆点
}

export function PersonalInfoHeader({ info, onChange, isRaw = false }: PersonalInfoHeaderProps) {
  const updateField = (id: string, key: 'label' | 'value', val: string) => {
    onChange({
      ...info,
      fields: info.fields.map(f => f.id === id ? { ...f, [key]: val } : f)
    })
  }

  const addField = () => {
    onChange({
      ...info,
      fields: [...info.fields, { id: `field-${Date.now()}`, label: "自定义", value: "填写内容" }]
    })
  }

  const removeField = (id: string) => {
    onChange({
      ...info,
      fields: info.fields.filter(f => f.id !== id)
    })
  }

  return (
    <section className="relative overflow-hidden rounded-2xl border border-indigo-100/50 bg-gradient-to-br from-white via-slate-50 to-indigo-50/30 p-6 shadow-sm ring-1 ring-slate-200/50">
      
      {/* 顶部装饰条 */}
      <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-indigo-500 via-purple-500 to-indigo-500 opacity-80" />

      <div className="flex flex-col gap-6 sm:flex-row sm:items-start">
        
        {/* 左侧头像与核心信息区 */}
        <div className="flex flex-1 items-start gap-5">
          {/* 头像占位符 */}
          <div className="group relative flex size-20 shrink-0 cursor-not-allowed items-center justify-center rounded-full border-2 border-indigo-100 bg-white shadow-sm transition-all hover:shadow-md sm:size-24">
            <UserCircle2 className="size-10 text-indigo-200 sm:size-12" />
            <div className="absolute inset-0 flex items-center justify-center rounded-full bg-black/40 opacity-0 transition-opacity group-hover:opacity-100">
              <span className="text-[10px] font-medium text-white">暂不支持上传</span>
            </div>
          </div>

          {/* 姓名与职位 */}
          <div className="flex w-full flex-col gap-1.5 pt-1">
            <Input
              value={info.name}
              onChange={(e) => onChange({ ...info, name: e.target.value })}
              readOnly={isRaw}
              placeholder="您的姓名"
              className={cn(
                "h-auto border-0 bg-transparent p-0 text-2xl font-black tracking-tight text-slate-800 placeholder:text-slate-300 focus-visible:ring-0 sm:text-3xl",
                !isRaw && "hover:bg-slate-100/50 focus:bg-white focus:px-2 focus:ring-1 focus:ring-indigo-300 rounded"
              )}
            />
            <Input
              value={info.jobTitle}
              onChange={(e) => onChange({ ...info, jobTitle: e.target.value })}
              readOnly={isRaw}
              placeholder="求职意向 / 职位名称"
              className={cn(
                "h-auto border-0 bg-transparent p-0 text-sm font-semibold text-indigo-600 placeholder:text-indigo-200 focus-visible:ring-0",
                !isRaw && "hover:bg-indigo-50/50 focus:bg-white focus:px-2 focus:ring-1 focus:ring-indigo-300 rounded"
              )}
            />
          </div>
        </div>

        {/* 右侧详细字段区 */}
        <div className="flex w-full flex-col gap-2 sm:w-[320px] shrink-0">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 pl-1 border-b border-slate-200 pb-1 mb-1">
            联系方式 & 详细信息
          </div>
          
          <div className="flex flex-col gap-1">
            {info.fields.map((field) => (
              <div key={field.id} className="group relative flex items-center gap-2 rounded hover:bg-slate-100/50 px-1 py-0.5">
                <div className="flex w-[72px] shrink-0 items-center gap-1.5 text-slate-500">
                  <div className="flex size-4 items-center justify-center text-slate-400">
                    {getFieldIcon(field.label)}
                  </div>
                  <Input
                    value={field.label}
                    onChange={(e) => updateField(field.id, 'label', e.target.value)}
                    readOnly={isRaw}
                    className="h-6 border-0 bg-transparent p-0 text-[11px] font-medium focus-visible:ring-0 focus-visible:ring-offset-0 focus:bg-white focus:px-1 rounded w-full"
                  />
                </div>
                
                <span className="text-slate-300">:</span>

                <Input
                  value={field.value}
                  onChange={(e) => updateField(field.id, 'value', e.target.value)}
                  readOnly={isRaw}
                  className="h-6 flex-1 border-0 bg-transparent p-0 text-[12px] text-slate-700 focus-visible:ring-0 focus-visible:ring-offset-0 focus:bg-white focus:px-1 rounded"
                />

                {!isRaw && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-5 absolute right-0 opacity-0 group-hover:opacity-100 text-slate-300 hover:text-red-500 hover:bg-red-50"
                    onClick={() => removeField(field.id)}
                  >
                    <X className="size-3" />
                  </Button>
                )}
              </div>
            ))}
          </div>

          {!isRaw && (
            <Button
              variant="ghost"
              size="sm"
              onClick={addField}
              className="mt-1 h-6 w-fit gap-1 px-2 text-[11px] text-indigo-500 hover:bg-indigo-50 hover:text-indigo-600"
            >
              <Plus className="size-3" />
              添加字段
            </Button>
          )}
        </div>

      </div>
    </section>
  )
}
