import React from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"

export function SummaryCard() {
  const { resumeData, updateSummary } = useResumeV2Store()
  if (!resumeData) return null

  return (
    <Card className="shadow-sm">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg font-semibold">个人总结 / Professional Summary</CardTitle>
      </CardHeader>
      <CardContent>
        <Textarea 
          value={resumeData.summary || ''} 
          onChange={(e) => updateSummary(e.target.value)}
          placeholder="A brief overview of your professional background, key achievements, and career goals."
          className="min-h-[120px] resize-y"
        />
      </CardContent>
    </Card>
  )
}
