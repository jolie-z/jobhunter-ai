"use client"

import { API_BASE } from "@/lib/api"
import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Sparkles } from "lucide-react"
import { useToast } from "@/hooks/use-toast"
import { BossTab } from "./boss-tab"
import { LiepinTab } from "./liepin-tab"
import { Job51Tab } from "./51job-tab"
import { ZhilianTab } from "./zhilian-tab"
import { ResumeActionBar, PLATFORM_NAMES } from "./resume-action-bar"
import { SchemaDiffDrawer, type SchemaDiffReport } from "@/components/ui/schema-diff-drawer"
import { useEdgeLaunchGuard } from "@/hooks/use-edge-launch-guard"
import { isEdgeMissing } from "@/lib/platform-auth"

interface ResumeField {
  label: string
  required: boolean
  type: string
  options?: string[]
  max_length?: number
  current_value: any
  fields?: Record<string, ResumeField>
}

interface ResumeData {
  [key: string]: ResumeField
}


export default function ResumeEditorPage() {
  const [bossData, setBossData] = useState<ResumeData | null>(null)
  const [liepinData, setLiepinData] = useState<ResumeData | null>(null)
  const [job51Data, setJob51Data] = useState<ResumeData | null>(null)
  const [zhilianData, setZhilianData] = useState<ResumeData | null>(null)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState<string | null>(null)
  const [collecting, setCollecting] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<string>("boss")
  const [selectedPlatforms, setSelectedPlatforms] = useState({
    boss: true,
    liepin: true,
    "51job": true,
    zhilian: true,
  })
  const [platformStatus, setPlatformStatus] = useState<Record<string, { port: number; online: boolean; logged_in: boolean }>>({})
  const [launchingPlatform, setLaunchingPlatform] = useState<string | null>(null)
  const [loginPlatform, setLoginPlatform] = useState<string | null>(null)
  const [statusRefreshing, setStatusRefreshing] = useState(false)
  const [deepVerifying, setDeepVerifying] = useState(false)
  // 全站统一 Toast 体系（@/hooks/use-toast，与模块三/四一致）；showToast 保持旧签名供子组件复用
  const { toast } = useToast()
  // 报告生成后 +1，通知各平台 tab 刷新自己的映射报告
  const [reportVersion, setReportVersion] = useState(0)
  // Schema 模版自适应差分检测
  const [activeDiff, setActiveDiff] = useState<SchemaDiffReport | null>(null)
  const [pendingDiffs, setPendingDiffs] = useState<SchemaDiffReport[]>([])

  const showToast = (message: string, type: "success" | "error" | "info" = "info") => {
    toast({
      title: message,
      variant: type === "error" ? "destructive" : undefined,
    })
  }

  // Edge 未安装守卫：唤起前探测，未装弹「下载 Edge」引导
  const { guardLaunch, edgeDialog } = useEdgeLaunchGuard()

  // 探测各平台浏览器状态
  const checkPlatformStatus = async (showToastFeedback = false) => {
    setStatusRefreshing(true)
    try {
      const res = await fetch(`${API_BASE}/api/platforms/status`)
      const result = await res.json()
      if (result.success) {
        setPlatformStatus(result.platforms)
        if (showToastFeedback) {
          showToast("各平台浏览器与登录状态已刷新为最新", "success")
        }
      } else {
        if (showToastFeedback) {
          showToast(result.message || "获取登录状态失败", "error")
        }
      }
    } catch (e: any) {
      if (showToastFeedback) {
        showToast("刷新状态网络异常: " + (e?.message || e), "error")
      }
    } finally {
      setStatusRefreshing(false)
    }
  }

  // 深度校验：DOM 级登录态判定（权威但较慢），结果覆盖轻量状态栏
  const handleDeepVerify = async () => {
    setDeepVerifying(true)
    try {
      const res = await fetch(`${API_BASE}/api/platforms/status/deep`, { method: "POST" })
      const result = await res.json()
      if (result.success) {
        setPlatformStatus((prev) => ({ ...prev, ...result.platforms }))
        const vals = Object.values(result.platforms) as Array<{ online: boolean; logged_in: boolean }>
        const loggedIn = vals.filter((s) => s.logged_in).length
        const offline = vals.filter((s) => !s.online).length
        const summary = offline > 0
          ? `已登录 ${loggedIn}/${vals.length}，${offline} 个浏览器未启动`
          : `已登录 ${loggedIn}/${vals.length}`
        showToast(`深度校验完成：${summary}`, loggedIn === vals.length ? "success" : "info")
      } else {
        showToast(result.message || "深度校验失败", "error")
      }
    } catch (e: any) {
      showToast("深度校验网络异常: " + (e?.message || e), "error")
    } finally {
      setDeepVerifying(false)
    }
  }

  const launchBrowser = async (platform: string) => {
    setLaunchingPlatform(platform)
    try {
      const result = await guardLaunch(async () => {
        const res = await fetch(`${API_BASE}/api/platforms/launch`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ platform }),
        })
        const r = await res.json()
        if (r.success) return { ok: true as const, message: r.message || "" }
        // code=edge_not_installed（本机未装 Edge）时守卫会弹下载引导
        return { ok: false as const, message: r.message || "启动失败", code: r.code, downloadUrl: r.download_url }
      })
      if (result.ok) {
        showToast(`正在启动 ${PLATFORM_NAMES[platform as keyof typeof PLATFORM_NAMES]} 浏览器...`, "info")
        setTimeout(checkPlatformStatus, 3000)
      } else if (!isEdgeMissing(result)) {
        showToast(result.message, "error")
      }
    } catch (e) {
      showToast("启动失败: " + e, "error")
    } finally {
      setLaunchingPlatform(null)
    }
  }

  const gotoLogin = async (platform: string) => {
    setLoginPlatform(platform)
    try {
      const res = await fetch(`${API_BASE}/api/platforms/goto-login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform }),
      })
      const result = await res.json()
      if (result.success) {
        showToast(`正在打开 ${PLATFORM_NAMES[platform as keyof typeof PLATFORM_NAMES]} 登录页...`, "info")
      } else {
        showToast(result.message || "跳转登录失败", "error")
      }
    } catch (e) {
      showToast("跳转登录失败: " + e, "error")
    } finally {
      setLoginPlatform(null)
    }
  }

  const getSelectedPlatforms = () => {
    return Object.entries(selectedPlatforms)
      .filter(([, v]) => v)
      .map(([k]) => k)
  }

  // 批量采集数据
  const handleUnifiedCollect = async () => {
    const platforms = getSelectedPlatforms()
    if (platforms.length === 0) {
      showToast("请至少选择一个平台", "error")
      return
    }
    setCollecting("all")
    try {
      const res = await fetch(`${API_BASE}/api/unified/collect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platforms }),
      })
      const result = await res.json()
      if (result.success) {
        await loadAllData()
        const diffs: SchemaDiffReport[] = []
        if (Array.isArray(result.results)) {
          result.results.forEach((r: any) => {
            if (r.schema_diff && r.schema_diff.has_changes) {
              diffs.push(r.schema_diff)
            }
          })
        }
        if (diffs.length > 0) {
          setPendingDiffs(diffs)
          showToast(`采集完成！检测到 ${diffs.length} 个平台的在线模版有结构变动，建议查看并同步。`, "info")
        } else {
          showToast(`采集完成，已成功采集 ${platforms.length} 个平台的数据`, "success")
        }
      } else {
        // 部分失败也刷新（成功平台的数据已更新），并逐个展示失败平台的具体原因
        await loadAllData()
        const failed = (Array.isArray(result.results) ? result.results : []).filter((r: any) => !r.success)
        if (failed.length > 0) {
          const succeeded = platforms.length - failed.length
          const detail = failed
            .map((r: any) => {
              const name = PLATFORM_NAMES[r.platform as keyof typeof PLATFORM_NAMES] || r.platform
              const reason = String(r.message || "失败").replace(/^\[ERROR\]\s*/, "").slice(0, 90)
              return `${name}采集失败：${reason}`
            })
            .join("；")
          const tail = succeeded > 0 ? `；其余${succeeded}个平台采集成功` : "，请检查后重试"
          showToast(detail + tail, "error")
        } else {
          showToast(result.message || "部分平台采集失败", "error")
        }
      }
    } catch (e) {
      showToast("采集请求失败: " + e, "error")
    } finally {
      setCollecting(null)
    }
  }

  // 批量回写数据
  const handleUnifiedSyncBack = async () => {
    const platforms = getSelectedPlatforms()
    if (platforms.length === 0) {
      showToast("请至少选择一个平台", "error")
      return
    }
    const names = platforms.map((p) => PLATFORM_NAMES[p as keyof typeof PLATFORM_NAMES]).join("、")
    if (!window.confirm(`确定要回写 ${names} 的官网在线简历吗？\n\n· 数据源：已保存的回写快照（未保存则用本地数据）\n· 全模块覆盖，按平台顺序执行\n· 如刚应用映射，请先在各 Tab 点「保存快照」`)) {
      return
    }
    setSyncing("all")
    try {
      const res = await fetch(`${API_BASE}/api/unified/sync-back`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platforms }),
      })
      const result = await res.json()
      if (result.success) {
        showToast(`✓ ${result.message || `已成功回写 ${platforms.length} 个平台`}`, "success")
      } else {
        // 逐平台展示失败原因；崩溃类失败（无 RESULT_JSON）追回 stderr 末行（异常本体）；
        // 成功平台也汇总展示，避免"某平台去哪了"的困惑
        const failed = (Array.isArray(result.results) ? result.results : []).filter((r: any) => !r.success)
        const okNames = (Array.isArray(result.results) ? result.results : [])
          .filter((r: any) => r.success)
          .map((r: any) => PLATFORM_NAMES[r.platform as keyof typeof PLATFORM_NAMES] || r.platform)
        if (failed.length > 0) {
          const detail =
            failed
              .map((r: any) => {
                const name = PLATFORM_NAMES[r.platform as keyof typeof PLATFORM_NAMES] || r.platform
                let reason = String(r.message || "失败").slice(0, 70)
                if (r.stderr) {
                  const lines = String(r.stderr).split("\n").map((l: string) => l.trim()).filter(Boolean)
                  const errLine = lines[lines.length - 1]
                  if (errLine) reason += `（${errLine.slice(0, 90)}）`
                }
                return `${name}：${reason}`
              })
              .join("；")
          showToast(okNames.length > 0 ? `${detail}；其余成功：${okNames.join("、")}` : detail, "error")
        } else {
          showToast(result.message || "部分平台回写失败", "error")
        }
      }
    } catch (e) {
      showToast("回写请求失败: " + e, "error")
    } finally {
      setSyncing(null)
    }
  }

  // 清空本地数据
  const handleClearData = async () => {
    const platforms = getSelectedPlatforms()
    if (platforms.length === 0) {
      showToast("请至少选择一个平台", "error")
      return
    }
    const names = platforms.map((p) => PLATFORM_NAMES[p as keyof typeof PLATFORM_NAMES]).join("、")
    if (!window.confirm(`确定要清空 ${names} 的本地数据吗？（不影响官网在线数据）`)) {
      return
    }
    try {
      const res = await fetch(`${API_BASE}/api/platforms/clear-data`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platforms }),
      })
      const result = await res.json()
      if (result.success) {
        if (platforms.includes("boss")) setBossData(null)
        if (platforms.includes("liepin")) setLiepinData(null)
        if (platforms.includes("51job")) setJob51Data(null)
        if (platforms.includes("zhilian")) setZhilianData(null)
        showToast(`已清空 ${result.cleared.length} 个平台的数据`, "success")
      } else {
        showToast(result.message || "清空失败", "error")
      }
    } catch (e) {
      showToast("清空失败: " + e, "error")
    }
  }

  // 加载数据
  useEffect(() => {
    loadAllData()
    checkPlatformStatus()
  }, [])

  const loadAllData = async () => {
    setLoading(true)
    try {
      const [bossRes, liepinRes, job51Res, zhilianRes] = await Promise.all([
        fetch(`${API_BASE}/api/resume-editor/boss`).then((r) => r.json()),
        fetch(`${API_BASE}/api/resume-editor/liepin`).then((r) => r.json()),
        fetch(`${API_BASE}/api/resume-editor/51job`).then((r) => r.json()),
        fetch(`${API_BASE}/api/resume-editor/zhilian`).then((r) => r.json()),
      ])

      if (bossRes.success) setBossData(bossRes.data)
      if (liepinRes.success) setLiepinData(liepinRes.data)
      if (job51Res.success) setJob51Data(job51Res.data)
      if (zhilianRes.success) setZhilianData(zhilianRes.data)
    } catch (error) {
      console.error("加载数据失败:", error)
    } finally {
      setLoading(false)
    }
  }

  // 按选择刷新数据
  const handleRefreshData = async () => {
    const platforms = getSelectedPlatforms()
    if (platforms.length === 0) {
      showToast("请至少选择一个平台", "error")
      return
    }
    setLoading(true)
    try {
      const API_MAP: Record<string, [string, (d: any) => void]> = {
        boss: ["/api/resume-editor/boss", setBossData],
        liepin: ["/api/resume-editor/liepin", setLiepinData],
        "51job": ["/api/resume-editor/51job", setJob51Data],
        zhilian: ["/api/resume-editor/zhilian", setZhilianData],
      }
      // 逐平台记录失败（数据不存在/后端异常），toast 不再无条件报成功
      const failed: string[] = []
      await Promise.all(
        platforms.map(async (p) => {
          const [path, setter] = API_MAP[p]
          try {
            const res = await fetch(`${API_BASE}${path}`)
            const data = await res.json()
            if (data.success) setter(data.data)
            else failed.push(PLATFORM_NAMES[p] || p)
          } catch (e) {
            console.error(`刷新 ${p} 失败:`, e)
            failed.push(PLATFORM_NAMES[p] || p)
          }
        })
      )
      if (failed.length > 0) {
        showToast(
          `刷新完成：${platforms.length - failed.length} 个成功；${failed.join("、")}失败（数据不存在或后端异常）`,
          "error"
        )
      } else {
        showToast(`已刷新 ${platforms.length} 个平台的数据`, "success")
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="container mx-auto py-6 max-w-7xl">
      {/* 全局调度操作栏（登录状态、批量操作、主简历映射与模块筛选） */}
      <ResumeActionBar
        apiBase={API_BASE}
        platformStatus={platformStatus}
        statusRefreshing={statusRefreshing}
        launchingPlatform={launchingPlatform}
        loginPlatform={loginPlatform}
        selectedPlatforms={selectedPlatforms}
        setSelectedPlatforms={setSelectedPlatforms}
        onCheckStatus={checkPlatformStatus}
        onLaunchBrowser={launchBrowser}
        onGotoLogin={gotoLogin}
        onDeepVerify={handleDeepVerify}
        deepVerifying={deepVerifying}
        onCollect={handleUnifiedCollect}
        onSyncBack={handleUnifiedSyncBack}
        onRefreshData={handleRefreshData}
        onClearData={handleClearData}
        collecting={collecting}
        syncing={syncing}
        showToast={showToast}
        onReportGenerated={() => setReportVersion(v => v + 1)}
      />

      {/* 模版自适应差分提醒横幅 */}
      {pendingDiffs.length > 0 && (
        <div className="mb-4 bg-gradient-to-r from-indigo-50 via-purple-50 to-blue-50 border border-indigo-200/80 rounded-xl p-3.5 shadow-sm flex items-center justify-between gap-3 animate-in fade-in duration-200">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-indigo-600 text-white flex items-center justify-center shrink-0">
              <Sparkles className="w-4 h-4 text-amber-300" />
            </div>
            <div>
              <div className="text-xs font-semibold text-indigo-950 flex items-center gap-2">
                <span>在线简历模版自适应检测到变动</span>
                <Badge variant="outline" className="bg-indigo-100/60 text-indigo-700 text-[10px] py-0 border-indigo-200">
                  {pendingDiffs.length} 个平台待同步
                </Badge>
              </div>
              <p className="text-[11px] text-indigo-800/80 mt-0.5">
                {pendingDiffs.map(d => `${PLATFORM_NAMES[d.platform] || d.platform}: ${d.summary}`).join("；")}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {pendingDiffs.map(d => (
              <Button
                key={d.platform}
                size="sm"
                variant="default"
                className="bg-indigo-600 hover:bg-indigo-700 text-white h-7 text-xs shadow-sm"
                onClick={() => setActiveDiff(d)}
              >
                <Sparkles className="w-3 h-3 mr-1 text-amber-300" />
                查看 {PLATFORM_NAMES[d.platform] || d.platform} 差分
              </Button>
            ))}
            <button
              type="button"
              onClick={() => setPendingDiffs([])}
              className="text-gray-400 hover:text-gray-600 p-1 text-sm"
              title="忽略所有"
            >
              ×
            </button>
          </div>
        </div>
      )}

      {/* 4 平台专属 Tab 切换 */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="boss">BOSS直聘</TabsTrigger>
          <TabsTrigger value="liepin">猎聘</TabsTrigger>
          <TabsTrigger value="51job">前程无忧</TabsTrigger>
          <TabsTrigger value="zhilian">智联招聘</TabsTrigger>
        </TabsList>

        <TabsContent value="boss">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>BOSS直聘简历数据</span>
                <Badge variant={bossData ? "default" : "secondary"}>{bossData ? "已加载" : "未加载"}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <BossTab data={bossData} loading={loading} onRefresh={loadAllData} reportVersion={reportVersion} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="liepin">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>猎聘简历数据</span>
                <Badge variant={liepinData ? "default" : "secondary"}>{liepinData ? "已加载" : "未加载"}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <LiepinTab data={liepinData} loading={loading} onRefresh={loadAllData} reportVersion={reportVersion} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="51job">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>前程无忧简历数据</span>
                <Badge variant={job51Data ? "default" : "secondary"}>{job51Data ? "已加载" : "未加载"}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <Job51Tab data={job51Data} loading={loading} onRefresh={loadAllData} reportVersion={reportVersion} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="zhilian">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>智联招聘简历数据</span>
                <Badge variant={zhilianData ? "default" : "secondary"}>{zhilianData ? "已加载" : "未加载"}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ZhilianTab data={zhilianData} loading={loading} onRefresh={loadAllData} reportVersion={reportVersion} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* 模版差分与自愈抽屉 */}
      {activeDiff && (
        <SchemaDiffDrawer
          isOpen={Boolean(activeDiff)}
          onClose={() => setActiveDiff(null)}
          diff={activeDiff}
          platformLabel={PLATFORM_NAMES[activeDiff.platform] || activeDiff.platform}
          apiBase={API_BASE}
          onSyncSuccess={() => {
            loadAllData()
            setPendingDiffs(prev => prev.filter(d => d.platform !== activeDiff.platform))
          }}
        />
      )}
      {edgeDialog}
    </div>
  )
}
