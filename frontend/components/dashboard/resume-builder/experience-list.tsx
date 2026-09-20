"use client"

import { Button } from "@/components/ui/button"
import { ExperienceItem } from "./experience-item"
import { Plus } from "lucide-react"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import type { ExperienceV2, ProjectV2, EducationV2 } from "@/types/resume"

interface ExperienceListProps {
  type: 'workExperience' | 'personalProjects' | 'education' | 'custom'
  moduleKey?: string
  wizardStep?: string
  atsQueue?: string[]
  syncQueue?: string[]
  grillQueue?: string[]
  onWizardComplete?: (tool: string, sectionId?: string) => void
}

export function ExperienceList({ type, moduleKey, wizardStep, atsQueue, syncQueue, grillQueue, onWizardComplete }: ExperienceListProps) {
  const store = useResumeV2Store()
  const { resumeData } = store
  if (!resumeData) return null

  const items = type === 'custom' && moduleKey 
    ? (resumeData.customModules?.[moduleKey] || [])
    : (resumeData[type as keyof typeof resumeData] as any[] || [])

  const handleUpdate = (index: number, patch: any) => {
    if (type === 'custom' && moduleKey) { store.updateCustomItem(moduleKey, index, patch); return; }
    if (type === 'workExperience') store.updateWorkExperience(index, patch)
    if (type === 'personalProjects') store.updateProject(index, patch)
    if (type === 'education') store.updateEducation(index, patch)
  }

  const handleDelete = (index: number) => {
    if (type === 'custom' && moduleKey) { store.removeCustomItem(moduleKey, index); return; }
    if (type === 'workExperience') store.removeWorkExperience(index)
    if (type === 'personalProjects') store.removeProject(index)
    if (type === 'education') store.removeEducation(index)
  }

  const handleAdd = () => {
    if (type === 'custom' && moduleKey) { store.addCustomItem(moduleKey, { title: "", company: "", years: "", description: [] }); return; }
    if (type === 'workExperience') store.addWorkExperience({ company: "", title: "", years: "", description: [] })
    if (type === 'personalProjects') store.addProject({ name: "", role: "", years: "", description: [] })
    if (type === 'education') store.addEducation({ institution: "", major: "", degree: "", years: "", description: "" })
  }

  const handleMoveUp = (index: number) => {
    if (index === 0) return;
    if (type === 'custom' && moduleKey) { store.reorderCustomItem(moduleKey, index, index - 1); return; }
    if (type === 'workExperience') store.reorderWorkExperience(index, index - 1)
    if (type === 'personalProjects') store.reorderProject(index, index - 1)
    if (type === 'education') store.reorderEducation(index, index - 1)
  }

  const handleMoveDown = (index: number) => {
    if (index === items.length - 1) return;
    if (type === 'custom' && moduleKey) { store.reorderCustomItem(moduleKey, index, index + 1); return; }
    if (type === 'workExperience') store.reorderWorkExperience(index, index + 1)
    if (type === 'personalProjects') store.reorderProject(index, index + 1)
    if (type === 'education') store.reorderEducation(index, index + 1)
  }
  
  let addLabel = "新增经历"
  if (type === 'education') addLabel = "新增教育"
  if (type === 'personalProjects') addLabel = "新增项目"

  return (
    <div className="flex flex-col gap-3">
      {items.map((item: any, index: number) => (
        <ExperienceItem
          key={item._key || index}
          item={item}
          index={index}
          
          
          
          
          moduleKey={moduleKey}
          type={type}
          wizardStep={wizardStep}
          grillQueue={grillQueue}
          atsQueue={atsQueue}
          syncQueue={syncQueue}
          onWizardComplete={onWizardComplete}
          onUpdate={(patch: any) => handleUpdate(index, patch)}
          onDelete={() => handleDelete(index)} 
          canMoveUp={index > 0}
          canMoveDown={index < items.length - 1}
          onMoveUp={() => handleMoveUp(index)}
          onMoveDown={() => handleMoveDown(index)}
        />
      ))}

      <Button
        variant="outline"
        onClick={handleAdd}
        className="h-11 w-full border-dashed bg-transparent text-muted-foreground hover:text-foreground"
      >
        <Plus className="mr-1.5 h-4 w-4" />
        {addLabel}
      </Button>
    </div>
  )
}
