import React from "react"
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Plus, Trash2, ArrowUp, ArrowDown } from "lucide-react"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"

export function ExperienceCard() {
  const { resumeData, addWorkExperience, updateWorkExperience, removeWorkExperience, reorderWorkExperience } = useResumeV2Store()
  if (!resumeData) return null

  const workExperience = resumeData.workExperience || []

  const handleAdd = () => {
    addWorkExperience({
      title: "",
      company: "",
      years: "",
      location: "",
      description: []
    })
  }

  const handleDescChange = (index: number, descIndex: number, val: string) => {
    const exp = workExperience[index]
    const newDesc = [...exp.description]
    newDesc[descIndex] = val
    updateWorkExperience(index, { description: newDesc })
  }

  const handleAddDesc = (index: number) => {
    const exp = workExperience[index]
    updateWorkExperience(index, { description: [...exp.description, ""] })
  }

  const handleRemoveDesc = (index: number, descIndex: number) => {
    const exp = workExperience[index]
    const newDesc = [...exp.description]
    newDesc.splice(descIndex, 1)
    updateWorkExperience(index, { description: newDesc })
  }

  return (
    <Card className="shadow-sm">
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="text-lg font-semibold">工作经历 / Work Experience</CardTitle>
        <Button variant="outline" size="sm" onClick={handleAdd}>
          <Plus className="w-4 h-4 mr-1" /> Add Experience
        </Button>
      </CardHeader>
      <CardContent className="space-y-6">
        {workExperience.map((exp, index) => (
          <div key={index} className="p-4 border rounded-md relative bg-muted/20">
            <div className="absolute right-2 top-2 flex items-center space-x-1">
              <Button variant="ghost" size="icon" disabled={index === 0} onClick={() => reorderWorkExperience(index, index - 1)}>
                <ArrowUp className="w-4 h-4 text-muted-foreground" />
              </Button>
              <Button variant="ghost" size="icon" disabled={index === workExperience.length - 1} onClick={() => reorderWorkExperience(index, index + 1)}>
                <ArrowDown className="w-4 h-4 text-muted-foreground" />
              </Button>
              <Button variant="ghost" size="icon" onClick={() => removeWorkExperience(index)}>
                <Trash2 className="w-4 h-4 text-destructive" />
              </Button>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
              <div className="space-y-2">
                <Label>公司 Company</Label>
                <Input 
                  value={exp.company} 
                  onChange={(e) => updateWorkExperience(index, { company: e.target.value })}
                  placeholder="Company Name"
                />
              </div>
              <div className="space-y-2">
                <Label>职位 Title</Label>
                <Input 
                  value={exp.title} 
                  onChange={(e) => updateWorkExperience(index, { title: e.target.value })}
                  placeholder="Job Title"
                />
              </div>
              <div className="space-y-2">
                <Label>时间 Date (e.g. 2020.09 - Present)</Label>
                <Input 
                  value={exp.years} 
                  onChange={(e) => updateWorkExperience(index, { years: e.target.value })}
                  placeholder="2020.09 - Present"
                />
              </div>
              <div className="space-y-2">
                <Label>城市 Location</Label>
                <Input 
                  value={exp.location || ''} 
                  onChange={(e) => updateWorkExperience(index, { location: e.target.value })}
                  placeholder="San Francisco, CA"
                />
              </div>
            </div>

            <div className="mt-4 space-y-2">
              <Label>工作描述 Description (Bullet Points)</Label>
              {exp.description.map((desc, dIndex) => (
                <div key={dIndex} className="flex gap-2 items-start">
                  <div className="mt-2 text-muted-foreground">•</div>
                  <Textarea 
                    value={desc}
                    onChange={(e) => handleDescChange(index, dIndex, e.target.value)}
                    className="min-h-[40px] flex-1 resize-y"
                    placeholder="Describe your achievements..."
                  />
                  <Button variant="ghost" size="icon" onClick={() => handleRemoveDesc(index, dIndex)} className="shrink-0">
                    <Trash2 className="w-4 h-4 text-muted-foreground hover:text-destructive" />
                  </Button>
                </div>
              ))}
              <Button variant="ghost" size="sm" onClick={() => handleAddDesc(index)} className="mt-2 text-primary">
                <Plus className="w-4 h-4 mr-1" /> Add Bullet Point
              </Button>
            </div>
          </div>
        ))}
        {workExperience.length === 0 && (
          <div className="text-center text-muted-foreground py-8">
            No work experience added yet.
          </div>
        )}
      </CardContent>
    </Card>
  )
}
