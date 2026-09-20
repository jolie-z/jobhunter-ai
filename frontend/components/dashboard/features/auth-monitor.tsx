import { useState, useEffect } from "react"
import { CheckCircle2, XCircle, Loader2, QrCode } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { toast } from "sonner"
import {
  fetchAuthStatus,
  fetchPlatformMeta,
  launchPlatformEdge,
  type AuthStatusMap,
  type PlatformMeta,
} from "@/lib/platform-auth"

// 徽章展示顺序与显示名（仅 UI 文案，端口等配置一律来自后端 registry）
const PLATFORM_ORDER: { key: string; label: string }[] = [
  { key: "boss", label: "BOSS 直聘" },
  { key: "zhilian", label: "智联招聘" },
  { key: "liepin", label: "猎聘网" },
  { key: "51job", label: "前程无忧" },
  { key: "xiaohongshu", label: "小红书" },
]

// 各平台弹窗主按钮配色（保持原有视觉）
const DIALOG_BUTTON_COLORS: Record<string, string> = {
  boss: "bg-[#18C3B1] hover:bg-[#14A696]",
  zhilian: "bg-blue-500 hover:bg-blue-600",
  liepin: "bg-green-500 hover:bg-green-600",
  "51job": "bg-orange-500 hover:bg-orange-600",
  xiaohongshu: "bg-red-500 hover:bg-red-600",
}

interface AuthMonitorProps {
  onStatusChange?: (status: AuthStatusMap | null) => void
}

export function AuthMonitor({ onStatusChange }: AuthMonitorProps = {}) {
  const [status, setStatus] = useState<AuthStatusMap | null>(null)
  const [checking, setChecking] = useState(true)
  // 平台端口元数据（后端唯一配置区提供，仅用于文案展示）
  const [metas, setMetas] = useState<PlatformMeta[]>([])

  // 授权弹窗：当前平台 + 唤起中 + Boss 等待登录态
  const [dialogPlatform, setDialogPlatform] = useState<string | null>(null)
  const [isLaunching, setIsLaunching] = useState(false)
  const [edgeLaunched, setEdgeLaunched] = useState(false)

  useEffect(() => {
    fetchPlatformMeta().then(setMetas).catch(() => {})
  }, [])

  // 🌟 动态轮询与焦点感知：当处于等待 Boss 登录态时开启 2s 高频轮询，并监听窗口切回焦点瞬间检测
  useEffect(() => {
    checkStatus()
    const isWaitingBoss = dialogPlatform === "boss" && edgeLaunched && !status?.boss?.logged_in
    const intervalMs = isWaitingBoss ? 2000 : 5000
    const timer = setInterval(checkStatus, intervalMs)

    const handleFocus = () => {
      if (document.visibilityState === "visible") {
        checkStatus()
      }
    }
    window.addEventListener("focus", handleFocus)
    document.addEventListener("visibilitychange", handleFocus)

    return () => {
      clearInterval(timer)
      window.removeEventListener("focus", handleFocus)
      document.removeEventListener("visibilitychange", handleFocus)
    }
  }, [dialogPlatform, edgeLaunched, status?.boss?.logged_in])

  // Boss 专属：唤起后停留在弹窗等待登录，检测到登录成功自动关窗 + toast
  useEffect(() => {
    if (dialogPlatform === "boss" && edgeLaunched && status?.boss?.logged_in) {
      setDialogPlatform(null)
      setEdgeLaunched(false)
      toast.success("Boss 直聘授权成功！")
    }
  }, [status?.boss?.logged_in, dialogPlatform, edgeLaunched])

  const checkStatus = async () => {
    setChecking(true)
    try {
      const currentStatus = await fetchAuthStatus()
      setStatus(currentStatus)
      onStatusChange?.(currentStatus)
    } catch (e) {
      console.error("Failed to fetch crawler status", e)
    } finally {
      setChecking(false)
    }
  }

  // 所有平台同一个唤起入口（后端按 registry 配置决定端口/profile/落地页）
  const handleLaunch = async (platform: string) => {
    try {
      setIsLaunching(true)
      const result = await launchPlatformEdge(platform)
      if (result.ok) {
        toast.success(result.message)
        if (platform === "boss") {
          setEdgeLaunched(true) // Boss 留在弹窗内等待登录，自动检测
        } else {
          setDialogPlatform(null)
        }
        checkStatus()
      } else {
        toast.error(result.message)
      }
    } catch (error) {
      console.error("Failed to launch platform edge:", error)
      toast.error("请求失败，请确保后端服务正常运行")
    } finally {
      setIsLaunching(false)
    }
  }

  const metaOf = (key: string) => metas.find((m) => m.key === key)
  const dialogMeta = dialogPlatform ? metaOf(dialogPlatform) : undefined
  const dialogLabel = PLATFORM_ORDER.find((p) => p.key === dialogPlatform)?.label ?? ""

  return (
    <>
      <section className="bg-white p-4 rounded-xl border border-gray-100 shadow-sm space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-800">平台登录授权状态</h3>
          <Button variant="ghost" size="sm" onClick={checkStatus} disabled={checking} className="h-6 text-xs text-blue-600">
            {checking ? "检查中..." : "刷新"}
          </Button>
        </div>
        <div className="flex flex-wrap gap-3 items-center text-sm">
          {PLATFORM_ORDER.map(({ key, label }) => (
            <StatusBadge
              key={key}
              name={label}
              active={status?.[key]?.logged_in}
              checking={checking}
              onAuthClick={() => setDialogPlatform(key)}
            />
          ))}
        </div>
      </section>

      {/* 统一授权弹窗（五个平台共用同一套唤起逻辑，端口文案来自后端配置区） */}
      <Dialog
        open={!!dialogPlatform}
        onOpenChange={(open) => {
          if (!open) {
            setDialogPlatform(null)
            setEdgeLaunched(false)
          }
        }}
      >
        <DialogContent className="sm:max-w-md z-[200]">
          <DialogHeader>
            <DialogTitle>{dialogLabel} 真机接管模式</DialogTitle>
            <DialogDescription>
              唤起本地独立隔离环境的 Edge 浏览器，完成{dialogLabel}登录。
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col space-y-4 pt-4">
            {dialogPlatform === "boss" && edgeLaunched ? (
              <div className="flex flex-col items-center text-center p-6 space-y-4">
                <Loader2 className="h-8 w-8 animate-spin text-[#18C3B1]" />
                <p className="text-sm font-medium text-slate-700">等待登录 Boss 直聘...</p>
                <p className="text-xs text-slate-500">
                  请在已打开的 Edge 浏览器中完成登录，系统将每 5 秒自动检测登录状态。登录成功后此窗口将自动关闭。
                </p>
              </div>
            ) : (
              <div className="p-4 bg-slate-50 rounded-lg text-sm text-slate-700 space-y-3">
                <p>
                  爬虫将直接调用您本地的{" "}
                  <strong>Edge 浏览器{dialogMeta ? `（端口 ${dialogMeta.port}）` : ""}</strong>
                  。请点击下方按钮唤起浏览器并完成登录，登录成功后关闭该弹窗并点击「刷新」即可。
                </p>
                <div className="flex justify-center py-2">
                  <Button
                    onClick={() => dialogPlatform && handleLaunch(dialogPlatform)}
                    disabled={isLaunching}
                    className={`w-full text-white font-medium ${DIALOG_BUTTON_COLORS[dialogPlatform ?? ""] ?? "bg-slate-700 hover:bg-slate-600"}`}
                  >
                    {isLaunching ? (
                      <span className="flex items-center gap-2">
                        <span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full"></span>
                        正在唤起真机...
                      </span>
                    ) : (
                      `一键唤起 Edge 浏览器 (${dialogLabel})`
                    )}
                  </Button>
                </div>
                <p className="text-xs text-slate-500 mt-2">
                  * 如果唤起失败，请确认您已安装 Edge 浏览器。
                </p>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}

export function StatusBadge({ name, active, checking, onAuthClick }: { name: string; active?: boolean; checking: boolean; onAuthClick?: () => void }) {
  if (checking) return <div className="flex items-center gap-1 text-gray-400"><Loader2 className="h-3 w-3 animate-spin"/>{name}</div>
  
  if (active) {
    return (
      <div className="flex items-center gap-1.5 text-green-600 font-medium bg-green-50 px-2 py-1 rounded-md">
        <CheckCircle2 className="h-3.5 w-3.5" />
        {name}
      </div>
    )
  }
  
  return (
    <div className="flex items-center gap-1.5 text-red-500 font-medium bg-red-50 px-2 py-1 rounded-md group relative">
      <XCircle className="h-3.5 w-3.5" />
      {name}
      {onAuthClick && (
        <button 
          type="button"
          onClick={onAuthClick}
          className="ml-1 text-[10px] bg-red-100 text-red-600 px-1.5 py-0.5 rounded shadow-sm hover:bg-red-200 transition-colors flex items-center gap-0.5"
        >
          <QrCode className="w-3 h-3" /> 授权
        </button>
      )}
    </div>
  )
}
