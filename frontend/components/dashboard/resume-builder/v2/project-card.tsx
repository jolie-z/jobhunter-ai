import React from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Plus, Trash2, ArrowUp, ArrowDown } from "lucide-react"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"

export function ProjectCard() {
  const { resumeData, addProject, updateProject, removeProject, reorderProject } = useResumeV2Store()
  if (!resumeData) return null

  const personalProjects = resumeData.personalProjects || []

  const handleAdd = () => {
    addProject({
      name: "",
      role: "",
      years: "",
      description: []
    })
  }

  const handleDescChange = (index: number, descIndex: number, val: string) => {
    const proj = personalProjects[index]
    const newDesc = [...proj.description]
    newDesc[descIndex] = val
    updateProject(index, { description: newDesc })
  }

  const handleAddDesc = (index: number) => {
    const proj = personalProjects[index]
    updateProject(index, { description: [...proj.description, ""] })
  }

  const handleRemoveDesc = (index: number, descIndex: number) => {
    const proj = personalProjects[index]
    const newDesc = [...proj.description]
    newDesc.splice(descIndex, 1)
    updateProject(index, { description: newDesc })
  }

  return (
    <Card className="shadow-sm">
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="text-lg font-semibold">项目经历 / Personal Projects</CardTitle>
        <Button variant="outline" size="sm" onClick={handleAdd}>
          <Plus className="w-4 h-4 mr-1" /> Add Project
        </Button>
      </CardHeader>
      <CardContent className="space-y-6">
        {personalProjects.map((proj, index) => (
          <div key={index} className="p-4 border rounded-md relative bg-muted/20">
            <div className="absolute right-2 top-2 flex items-center space-x-1">
              <Button variant="ghost" size="icon" disabled={index === 0} onClick={() => reorderProject(index, index - 1)}>
                <ArrowUp className="w-4 h-4 text-muted-foreground" />
              </Button>
              <Button variant="ghost" size="icon" disabled={index === personalProjects.length - 1} onClick={() => reorderProject(index, index + 1)}>
                <ArrowDown className="w-4 h-4 text-muted-foreground" />
              </Button>
              <Button variant="ghost" size="icon" onClick={() => removeProject(index)}>
                <Trash2 className="w-4 h-4 text-destructive" />
              </Button>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
              <div className="space-y-2">
                <Label>项目名称 Project Name</Label>
                <Input 
                  value={proj.name} 
                  onChange={(e) => updateProject(index, { name: e.target.value })}
                  placeholder="Project Name"
                />
              </div>
              <div className="space-y-2">
                <Label>担任角色 Role</Label>
                <Input 
                  value={proj.role} 
                  onChange={(e) => updateProject(index, { role: e.target.value })}
                  placeholder="Role"
                />
              </div>
              <div className="space-y-2">
                <Label>时间 Date (e.g. 2020.09 - 2021.05)</Label>
                <Input 
                  value={proj.years} 
                  onChange={(e) => updateProject(index, { years: e.target.value })}
                  placeholder="2020.09 - 2021.05"
                />
              </div>
            </div>

            <div className="mt-4 space-y-2">
              <Label>项目描述 Description (Bullet Points)</Label>
              {proj.description.map((desc, dIndex) => (
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
        {personalProjects.length === 0 && (
          <div className="text-center text-muted-foreground py-8">
            No projects added yet.
          </div>
        )}
      </CardContent>
    </Card>
  )
}
