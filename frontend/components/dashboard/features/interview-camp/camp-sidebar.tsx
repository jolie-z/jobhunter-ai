import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Building2, ArrowLeft, FileText } from "lucide-react"
import { JobArchiveColumn } from "../job-archive-column"
import type { JobData } from "@/types/job"

interface CampSidebarProps {
  interviewJobs: JobData[]
  activeJobId: string
  setActiveJobId: (id: string) => void
  activeJob: JobData | undefined
  showList: boolean
  setShowList: (val: boolean) => void
}

export function CampSidebar({
  interviewJobs,
  activeJobId,
  setActiveJobId,
  activeJob,
  showList,
  setShowList
}: CampSidebarProps) {
  return (
    <div className="w-80 shrink-0 h-full bg-white rounded-xl shadow-sm border overflow-hidden flex flex-col transition-all duration-300">
      {showList ? (
        <div className="flex flex-col h-full">
          <div className="p-4 border-b bg-gray-50 flex items-center justify-between shrink-0">
            <h2 className="font-bold text-gray-800 flex items-center gap-2">
              <Building2 className="h-5 w-5 text-blue-600" /> 待战列表 ({interviewJobs.length})
            </h2>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-3 custom-scrollbar">
            {interviewJobs.map((job) => (
              <Card 
                key={job.id} 
                className={`cursor-pointer transition-all hover:border-blue-400 ${activeJobId === job.id ? "border-blue-500 bg-blue-50 shadow-md ring-1 ring-blue-200" : ""}`}
                onClick={() => {
                  setActiveJobId(job.id)
                  setShowList(false) // 点击后自动隐藏列表显示档案
                }}
              >
                <CardContent className="p-4">
                  <div className="flex justify-between items-start mb-2">
                    <span className="font-bold text-sm text-gray-900 truncate pr-2">{job.companyName}</span>
                    <span className="text-[10px] font-bold bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full shrink-0">{job.followStatus}</span>
                  </div>
                  <p className="text-xs text-gray-500 truncate">{job.jobTitle}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex flex-col h-full">
          <div className="p-3 border-b bg-gray-50 flex items-center shrink-0">
            <Button variant="ghost" size="sm" onClick={() => setShowList(true)} className="text-blue-600 hover:text-blue-700 hover:bg-blue-50">
              <ArrowLeft className="w-4 h-4 mr-1.5"/> 返回待战列表
            </Button>
          </div>
          <div className="flex-1 overflow-y-auto p-0 custom-scrollbar relative">
            <JobArchiveColumn job={activeJob || null} />
          </div>
        </div>
      )}
    </div>
  )
}
