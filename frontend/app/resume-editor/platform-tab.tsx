"use client"

import { API_BASE } from "@/lib/api"
import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Loader2, Edit, Save, X } from "lucide-react"


interface ResumeField {
  label: string
  required: boolean
  type: string
  options?: string[]
  max_length?: number
  current_value: any
  fields?: Record<string, ResumeField>
}

interface ResumeData {
  [key: string]: ResumeField
}

interface PlatformTabProps {
  platform: string
  platformName: string
  data: ResumeData | null
  loading: boolean
  onRefresh: () => void
}

export function PlatformTab({ platform, platformName, data, loading, onRefresh }: PlatformTabProps) {
  const [editingField, setEditingField] = useState<string | null>(null)
  const [editValue, setEditValue] = useState<any>(null)
  const [saving, setSaving] = useState(false)

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-8 h-8 animate-spin" />
        <span className="ml-2">加载中...</span>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="text-center py-12 text-gray-500">
        <div className="text-4xl mb-4">📭</div>
        <div>暂无{platformName}数据</div>
        <div className="text-sm mt-2">请先运行采集脚本</div>
        <Button onClick={onRefresh} className="mt-4">
          刷新数据
        </Button>
      </div>
    )
  }

  // 开始编辑
  const startEdit = (fieldName: string, currentValue: any) => {
    setEditingField(fieldName)
    setEditValue(currentValue)
  }

  // 保存编辑
  const saveEdit = async (fieldName: string) => {
    setSaving(true)
    try {
      const updatedData = {
        ...data,
        [fieldName]: {
          ...data[fieldName],
          current_value: editValue,
        },
      }

      const response = await fetch(`${API_BASE}/api/resume-editor/save/${platform}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updatedData),
      })

      const result = await response.json()
      if (result.success) {
        setEditingField(null)
        setEditValue(null)
        onRefresh()
        alert("✅ 保存成功！")
      } else {
        alert(`❌ 保存失败: ${result.message}`)
      }
    } catch (error) {
      alert(`❌ 保存失败: ${error}`)
    } finally {
      setSaving(false)
    }
  }

  // 取消编辑
  const cancelEdit = () => {
    setEditingField(null)
    setEditValue(null)
  }

  // 渲染字段
  const renderField = (fieldName: string, field: ResumeField) => {
    const isEditing = editingField === fieldName
    const isTextarea = field.type === "textarea"
    const isArray = field.type === "array" && Array.isArray(field.current_value)

    return (
      <Card key={fieldName} className="mb-4">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">
              {field.label}
              {field.required && <span className="text-red-500 ml-1">*</span>}
              {isArray && (
                <Badge variant="secondary" className="ml-2">
                  {field.current_value.length}条
                </Badge>
              )}
            </CardTitle>
            {!isEditing && (
              <Button variant="ghost" size="sm" onClick={() => startEdit(fieldName, field.current_value)}>
                <Edit className="w-4 h-4 mr-1" />
                编辑
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {isEditing ? (
            <div className="space-y-2">
              {isTextarea ? (
                <Textarea
                  value={typeof editValue === 'string' ? editValue : JSON.stringify(editValue, null, 2)}
                  onChange={(e) => setEditValue(e.target.value)}
                  placeholder={`请输入${field.label}`}
                  rows={6}
                />
              ) : isArray ? (
                <Textarea
                  value={JSON.stringify(editValue, null, 2)}
                  onChange={(e) => {
                    try {
                      setEditValue(JSON.parse(e.target.value))
                    } catch {
                      setEditValue(e.target.value)
                    }
                  }}
                  placeholder={`请输入${field.label}（JSON格式）`}
                  rows={10}
                />
              ) : (
                <Input
                  value={typeof editValue === 'string' ? editValue : JSON.stringify(editValue)}
                  onChange={(e) => setEditValue(e.target.value)}
                  placeholder={`请输入${field.label}`}
                />
              )}
              <div className="flex gap-2">
                <Button size="sm" onClick={() => saveEdit(fieldName)} disabled={saving}>
                  {saving ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Save className="w-4 h-4 mr-1" />}
                  保存
                </Button>
                <Button size="sm" variant="outline" onClick={cancelEdit}>
                  <X className="w-4 h-4 mr-1" />
                  取消
                </Button>
              </div>
            </div>
          ) : isArray ? (
            <div className="space-y-3">
              {field.current_value.map((item: any, index: number) => (
                <div key={index} className="p-3 border rounded-lg">
                  <div className="font-medium">
                    {item.company || item.project_name || item.school || item.cert_name || `记录 ${index + 1}`}
                  </div>
                  {item.position && <div className="text-sm text-gray-600">{item.position}</div>}
                  {item.period && <div className="text-sm text-gray-500">{item.period}</div>}
                  {item.description && <div className="text-sm text-gray-700 mt-2 line-clamp-2">{item.description}</div>}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-gray-700 whitespace-pre-wrap">
              {typeof field.current_value === 'string' ? field.current_value : JSON.stringify(field.current_value)}
            </div>
          )}
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {Object.entries(data).map(([fieldName, field]) => renderField(fieldName, field))}
    </div>
  )
}
