import React from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"

export function PersonalInfoCard() {
  const { resumeData, updatePersonalInfo } = useResumeV2Store()
  if (!resumeData) return null

  const personalInfo = resumeData.personalInfo || {}

  return (
    <Card className="shadow-sm">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg font-semibold">个人信息 / Personal Info</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>姓名 Name</Label>
          <Input 
            value={personalInfo.name || ''} 
            onChange={(e) => updatePersonalInfo({ name: e.target.value })}
            placeholder="John Doe"
          />
        </div>
        <div className="space-y-2">
          <Label>求职意向 Job Title</Label>
          <Input 
            value={personalInfo.title || ''} 
            onChange={(e) => updatePersonalInfo({ title: e.target.value })}
            placeholder="Software Engineer"
          />
        </div>
        <div className="space-y-2">
          <Label>手机号 Phone</Label>
          <Input 
            value={personalInfo.phone || ''} 
            onChange={(e) => updatePersonalInfo({ phone: e.target.value })}
            placeholder="138-0000-0000"
          />
        </div>
        <div className="space-y-2">
          <Label>邮箱 Email</Label>
          <Input 
            value={personalInfo.email || ''} 
            onChange={(e) => updatePersonalInfo({ email: e.target.value })}
            placeholder="john@example.com"
          />
        </div>
        <div className="space-y-2">
          <Label>所在城市 Location</Label>
          <Input 
            value={personalInfo.location || ''} 
            onChange={(e) => updatePersonalInfo({ location: e.target.value })}
            placeholder="Beijing, China"
          />
        </div>
        <div className="space-y-2">
          <Label>个人主页/博客 Website (Optional)</Label>
          <Input 
            value={personalInfo.website || ''} 
            onChange={(e) => updatePersonalInfo({ website: e.target.value })}
            placeholder="https://github.com/johndoe"
          />
        </div>
      </CardContent>
    </Card>
  )
}
