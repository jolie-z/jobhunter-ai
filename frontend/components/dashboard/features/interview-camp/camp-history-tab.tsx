import { useMemo } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Spinner } from "@/components/ui/spinner"
import { Activity, Calendar, FileText, X } from "lucide-react"
import ReactMarkdown from "react-markdown"
import { parseInterviewRecords, type InterviewRecordItem } from "@/lib/interview-record-parser"

interface CampHistoryTabProps {
  currentTranscript: string
  records?: InterviewRecordItem[]
  isRefreshingHistory: boolean
  refreshHistory: () => void
  handleDeleteRecord: (idOrBlock: string) => void
}

export function CampHistoryTab({
  currentTranscript,
  records,
  isRefreshingHistory,
  refreshHistory,
  handleDeleteRecord
}: CampHistoryTabProps) {
  // 🌟 结构化解析：优先使用 Hook 派生的强类型 records，兜底使用自适应解析器
  const displayRecords = useMemo(() => {
    return records || parseInterviewRecords(currentTranscript)
  }, [records, currentTranscript])

  return (
    <div className="flex-1 overflow-y-auto px-6 pb-6 m-0 custom-scrollbar">
      <Card className="border-indigo-100 bg-indigo-50/10 shadow-sm min-h-full flex flex-col">
        <CardHeader className="py-3 px-4 border-b border-indigo-50 bg-indigo-50/30 flex flex-row justify-between items-center shrink-0">
          <div>
            <CardTitle className="text-base text-indigo-900 flex items-center gap-2">
              🗄️ 历史面试复盘记录
            </CardTitle>
            <CardDescription className="text-xs mt-1 text-indigo-700/70">
              这里保存了你与 AI 所有的实战文字稿（存储于飞书总表）。
            </CardDescription>
          </div>
          <Button
            variant="outline" size="sm"
            onClick={refreshHistory} disabled={isRefreshingHistory}
            className="h-8 text-xs bg-white text-indigo-600 border-indigo-200 hover:bg-indigo-50 shadow-sm"
          >
            {isRefreshingHistory ? <Spinner className="w-3.5 h-3.5 mr-1" /> : <Activity className="w-3.5 h-3.5 mr-1" />}
            拉取云端记录
          </Button>
        </CardHeader>
        <CardContent className="p-6 flex-1 overflow-y-auto custom-scrollbar bg-gray-50/50">
          {displayRecords.length > 0 ? (
            <div className="space-y-6">
              {displayRecords.map((item) => (
                <div key={item.id} className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden relative group">
                  <div className="bg-indigo-50/50 px-4 py-2 border-b border-gray-100 flex justify-between items-center">
                    <div className="flex items-center gap-3">
                      <span className="font-bold text-indigo-900 text-xs flex items-center gap-1.5">
                        <Calendar className="w-3.5 h-3.5"/> {item.timestamp}
                      </span>
                      <div className="flex gap-1.5">
                        <Badge variant="outline" className="text-[10px] py-0 h-5 bg-white border-blue-200 text-blue-700">
                          {item.roleDisplay}
                        </Badge>
                        <Badge variant="outline" className="text-[10px] py-0 h-5 bg-white border-amber-200 text-amber-700">
                          {item.styleDisplay}
                        </Badge>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDeleteRecord(item.id)}
                      className="h-6 px-2 text-red-400 hover:text-red-600 hover:bg-red-50 opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <X className="w-3 h-3 mr-1"/> 删除记录
                    </Button>
                  </div>
                  <div className="p-4 text-[13px] text-gray-800 prose prose-sm max-w-none prose-headings:text-indigo-800 prose-headings:text-sm prose-p:my-1.5 prose-ul:my-1.5 prose-li:my-0.5">
                    <ReactMarkdown>{item.body}</ReactMarkdown>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center text-gray-400 py-20 h-full">
              <FileText size={48} className="opacity-20 mb-4" />
              <p>暂无历史面试记录，快去右侧进行一次语音对战吧！</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
