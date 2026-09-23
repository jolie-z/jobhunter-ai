"use client"

import { StrategyStoreProvider, useStrategyStore } from "@/hooks/use-strategy-store"
import { GlobalNav } from "@/components/dashboard/strategy-lab/global-nav"
import { SystemConfig } from "@/components/dashboard/strategy-lab/system-config"
import { ResumeBuilder } from "@/components/dashboard/resume-builder"
import { FeishuHub } from "@/components/dashboard/feishu-hub"

function SimpleHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <header className="sticky top-0 z-10 border-b border-slate-200/80 bg-white/80 px-6 py-3.5 backdrop-blur-md">
      <h1 className="text-base font-semibold text-slate-900">{title}</h1>
      <p className="text-xs text-slate-500">{subtitle}</p>
    </header>
  )
}

function PageInner() {
  const store = useStrategyStore()
  const { section, setSection } = store

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <GlobalNav active={section} onSelect={setSection} />

      {section === "resume" ? (
        <ResumeBuilder />
      ) : (
        <main className="flex min-w-0 flex-1 flex-col bg-slate-50/60">
          {section === "system" && (
            <>
              <SimpleHeader title="系统底层配置" subtitle="API 密钥与基础服务凭证" />
              <div className="flex-1 overflow-y-auto">
                <SystemConfig />
              </div>
            </>
          )}

          {section === "feishu" && (
            <FeishuHub />
          )}
        </main>
      )}

      {/* 全局 Toast */}
      {store.toastMsg && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-5 py-2.5 bg-gray-800 text-white text-sm rounded-full shadow-xl whitespace-nowrap">
          {store.toastMsg}
        </div>
      )}
    </div>
  )
}

export default function Page() {
  return (
    <StrategyStoreProvider>
      <PageInner />
    </StrategyStoreProvider>
  )
}
