"use client"

import { useState } from "react"
import { useTerminalStore } from "@/store/terminal-store"
import { LiveTaskTerminal } from "./live-task-terminal"
import { SpiderEngine } from "./features/spider-engine"
import { DataExplorer } from "./features/data-explorer"
import { Button } from "@/components/ui/button"
import { Minimize2, X, TerminalSquare, Bug, Database } from "lucide-react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

interface TerminalContainerProps {
  onComplete?: () => void
  onSseMessage?: (data: any) => void
}

export function TerminalContainer({ onComplete, onSseMessage }: TerminalContainerProps) {
  const { mode, minimize, closeTerminal1 } = useTerminalStore()
  const [activeTab, setActiveTab] = useState("logs")

  if (mode === 'minimize') return null

  return (
    <aside className="w-[380px] shrink-0 h-full border-l border-border bg-card overflow-hidden animate-in slide-in-from-right-4 duration-200 ease-out flex flex-col shadow-xl z-30 relative">
      
      {/* 工具栏 */}
      <div className="h-12 px-4 flex items-center justify-between border-b border-gray-100 bg-gradient-to-r from-gray-50 to-white shrink-0">
        <span className="text-sm font-medium text-gray-800">全景控制台</span>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0 text-gray-500 hover:text-gray-700 hover:bg-gray-100"
            onClick={minimize}
            title="最小化"
          >
            <Minimize2 className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0 text-gray-500 hover:text-red-600 hover:bg-red-50"
            onClick={closeTerminal1}
            title="关闭"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Tabs 内容区 */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col min-h-0 w-full">
        <div className="px-4 py-2 border-b border-gray-100 shrink-0 bg-white">
          <TabsList className="grid w-full grid-cols-3 h-8">
            <TabsTrigger value="logs" className="text-xs data-[state=active]:bg-blue-50 data-[state=active]:text-blue-600">
              <TerminalSquare className="w-3.5 h-3.5 mr-1" /> 日志流
            </TabsTrigger>
            <TabsTrigger value="spider" className="text-xs data-[state=active]:bg-indigo-50 data-[state=active]:text-indigo-600">
              <Bug className="w-3.5 h-3.5 mr-1" /> 蜘蛛引擎
            </TabsTrigger>
            <TabsTrigger value="database" className="text-xs data-[state=active]:bg-emerald-50 data-[state=active]:text-emerald-600">
              <Database className="w-3.5 h-3.5 mr-1" /> 数据探测
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="logs" className="flex-1 min-h-0 m-0 mt-0 data-[state=active]:flex flex-col border-none p-0 outline-none">
          <LiveTaskTerminal
            onComplete={onComplete}
            onMinimize={minimize}
            onClose={closeTerminal1}
            onSseMessage={onSseMessage}
            showInternalHeader={false}
          />
        </TabsContent>

        <TabsContent value="spider" className="flex-1 min-h-0 m-0 mt-0 data-[state=active]:block p-0 outline-none">
          <SpiderEngine onTaskStarted={() => setActiveTab("logs")} />
        </TabsContent>

        <TabsContent value="database" className="flex-1 min-h-0 m-0 mt-0 data-[state=active]:flex flex-col p-0 outline-none">
          <DataExplorer onTaskStarted={() => setActiveTab("logs")} />
        </TabsContent>
      </Tabs>
    </aside>
  )
}
