import React from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Button } from "@/components/ui/button"
import { Plus, Trash2, ArrowUp, ArrowDown } from "lucide-react"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"

export function EducationCard() {
  const { resumeData, addEducation, updateEducation, removeEducation, reorderEducation } = useResumeV2Store()
  if (!resumeData) return null

  const education = resumeData.education || []

  const handleAdd = () => {
    addEducation({
      institution: "",
      degree: "",
      years: "", major: "",
      description: ""
    })
  }

  return (
    <Card className="shadow-sm">
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="text-lg font-semibold">教育背景 / Education</CardTitle>
        <Button variant="outline" size="sm" onClick={handleAdd}>
          <Plus className="w-4 h-4 mr-1" /> Add Education
        </Button>
      </CardHeader>
      <CardContent className="space-y-6">
        {education.map((edu, index) => (
          <div key={index} className="p-4 border rounded-md relative bg-muted/20">
            <div className="absolute right-2 top-2 flex items-center space-x-1">
              <Button variant="ghost" size="icon" disabled={index === 0} onClick={() => reorderEducation(index, index - 1)}>
                <ArrowUp className="w-4 h-4 text-muted-foreground" />
              </Button>
              <Button variant="ghost" size="icon" disabled={index === education.length - 1} onClick={() => reorderEducation(index, index + 1)}>
                <ArrowDown className="w-4 h-4 text-muted-foreground" />
              </Button>
              <Button variant="ghost" size="icon" onClick={() => removeEducation(index)}>
                <Trash2 className="w-4 h-4 text-destructive" />
              </Button>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
              <div className="space-y-2">
                <Label>学校 Institution</Label>
                <Input 
                  value={edu.institution} 
                  onChange={(e) => updateEducation(index, { institution: e.target.value })}
                  placeholder="University Name"
                />
              </div>
              <div className="space-y-2">
                <Label>专业/学位 Degree</Label>
                <Input 
                  value={edu.degree} 
                  onChange={(e) => updateEducation(index, { degree: e.target.value })}
                  placeholder="B.S. in Computer Science"
                />
              </div>
              <div className="space-y-2">
                <Label>时间 Date (e.g. 2016.09 - 2020.06)</Label>
                <Input 
                  value={edu.years} 
                  onChange={(e) => updateEducation(index, { years: e.target.value })}
                  placeholder="2016.09 - 2020.06"
                />
              </div>
              <div className="space-y-2">
                <Label>补充描述 Description (Optional)</Label>
                <Input 
                  value={edu.description || ''} 
                  onChange={(e) => updateEducation(index, { description: e.target.value })}
                  placeholder="GPA: 3.8/4.0, Honors..."
                />
              </div>
            </div>
          </div>
        ))}
        {education.length === 0 && (
          <div className="text-center text-muted-foreground py-8">
            No education added yet.
          </div>
        )}
      </CardContent>
    </Card>
  )
}
