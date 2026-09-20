import React, { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Plus, X } from "lucide-react"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import type { AdditionalInfoV2 } from "@/types/resume"

export function AdditionalInfoCard() {
  const { resumeData, updateAdditional } = useResumeV2Store()
  if (!resumeData) return null

  const additional = resumeData.additional || { skills: [], languages: [] }

  const TagInput = ({ 
    label, 
    items, 
    field 
  }: { 
    label: string, 
    items: string[], 
    field: keyof AdditionalInfoV2 
  }) => {
    const [val, setVal] = useState("")

    const handleAdd = () => {
      if (!val.trim()) return
      updateAdditional({ [field]: [...items, val.trim()] })
      setVal("")
    }

    const handleRemove = (index: number) => {
      const newItems = [...items]
      newItems.splice(index, 1)
      updateAdditional({ [field]: newItems })
    }

    return (
      <div className="space-y-3">
        <Label>{label}</Label>
        <div className="flex flex-wrap gap-2 mb-2">
          {items.map((item, idx) => (
            <Badge key={idx} variant="secondary" className="px-3 py-1 text-sm font-normal">
              {item}
              <button onClick={() => handleRemove(idx)} className="ml-2 text-muted-foreground hover:text-foreground">
                <X className="w-3 h-3" />
              </button>
            </Badge>
          ))}
          {items.length === 0 && <span className="text-sm text-muted-foreground">None added</span>}
        </div>
        <div className="flex gap-2">
          <Input 
            value={val}
            onChange={(e) => setVal(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAdd(); } }}
            placeholder={`Add ${label.toLowerCase()}...`}
            className="max-w-sm"
          />
          <Button variant="secondary" onClick={handleAdd}>Add</Button>
        </div>
      </div>
    )
  }

  return (
    <Card className="shadow-sm">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg font-semibold">附加信息 / Additional Info</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <TagInput 
          label="专业技能 Technical Skills" 
          items={additional.technicalSkills || []} 
          field="technicalSkills" 
        />
        <TagInput 
          label="语言能力 Languages" 
          items={additional.languages || []} 
          field="languages" 
        />
        <TagInput 
          label="证书与培训 Certifications & Training" 
          items={additional.certificationsTraining || []} 
          field="certificationsTraining" 
        />
      </CardContent>
    </Card>
  )
}
