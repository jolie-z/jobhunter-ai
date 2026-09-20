import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import { useState, useEffect } from "react"
import { RefreshCw } from "lucide-react"
import { API_BASE } from "@/lib/api"

export interface PdfPreviewDialogProps {
  previewOpen: boolean
  setPreviewOpen: (open: boolean) => void
  avatarUrl?: string
}

const isDiyEnabled = process.env.NEXT_PUBLIC_ENABLE_DIY_TEMPLATE === "true"

const TEMPLATE_OPTIONS: Array<{ id: "classic" | "color" | "color_v2"; label: string }> = [
  { id: "classic", label: "普通模版" },
  { id: "color", label: "彩色模版" },
  ...(isDiyEnabled ? [{ id: "color_v2" as const, label: "DIY模版" }] : []),
]

export function PdfPreviewDialog({ previewOpen, setPreviewOpen, avatarUrl }: PdfPreviewDialogProps) {
  const { resumeData } = useResumeV2Store()
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [template, setTemplate] = useState<"classic" | "color" | "color_v2">("classic")

  useEffect(() => {
    if (!isDiyEnabled && template === "color_v2") {
      setTemplate("classic")
    }
  }, [template])

  useEffect(() => {
    let objectUrl: string | null = null;
    let isMounted = true;

    async function fetchPdf() {
      if (!previewOpen || !resumeData) {
        setPdfUrl(null);
        setError(null);
        return;
      }

      setIsGenerating(true)
      setError(null)
      try {
        let finalAvatarUrl = avatarUrl;
        
        // 如果外部没有传入 avatarUrl（比如在沉浸工作台中），则主动拉取一次全局配置来获取当前生效的头像
        if (!finalAvatarUrl) {
          try {
            const configRes = await fetch(`${API_BASE}/api/strategy/config`);
            if (configRes.ok) {
              const configData = await configRes.json();
              // 与全局枚举对齐：后端/侧栏用「启用」（index.tsx 兼容「启用中」），
              // 旧写法找「当前生效」永远匹配不到，导致兜底头像取不到
              const activeResume = configData.resumes?.find((r: any) => r.status === '启用' || r.status === '启用中');
              if (activeResume?.avatar_url) {
                finalAvatarUrl = activeResume.avatar_url;
              }
            }
          } catch (e) {
            console.error("Failed to fetch global avatar config", e);
          }
        }

        const payload = {
          resume_data: finalAvatarUrl ? { ...resumeData, avatar_url: finalAvatarUrl } : resumeData,
          page_size: "A4",
          template
        }
        
        const res = await fetch(`${API_BASE}/api/strategy/preview-pdf-direct`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify(payload)
        })

        if (!res.ok) {
          const text = await res.text();
          throw new Error(`生成失败: ${res.status} ${text}`);
        }

        const blob = await res.blob();
        if (isMounted) {
          objectUrl = URL.createObjectURL(blob);
          setPdfUrl(objectUrl);
        }
      } catch (err: any) {
        if (isMounted) {
          setError(err.message || "未知错误");
        }
      } finally {
        if (isMounted) {
          setIsGenerating(false);
        }
      }
    }

    fetchPdf();

    return () => {
      isMounted = false;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [previewOpen, resumeData, template]); // We re-fetch if they open it or if data/template changes

  return (
    <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
      <DialogContent className="sm:max-w-[800px] lg:max-w-[1000px] w-[95vw] h-[95vh] overflow-hidden p-0 bg-zinc-100 border-none rounded-lg shadow-2xl flex flex-col">
        <DialogTitle className="sr-only">PDF预览</DialogTitle>
        <DialogDescription className="sr-only">通过 Playwright 引擎实时渲染的物理 PDF 预览</DialogDescription>
        
        <div className="w-full h-full flex-1 relative bg-zinc-400">
          {/* 模版皮肤切换：普通(黑白) / 彩色模版 / DIY模版 */}
          <div className="absolute top-3 left-1/2 -translate-x-1/2 z-20 flex items-center rounded-full bg-white/95 shadow-lg border border-zinc-200 p-0.5">
            {TEMPLATE_OPTIONS.map((opt) => (
              <button
                key={opt.id}
                onClick={() => setTemplate(opt.id)}
                disabled={isGenerating}
                className={`px-3 py-1 text-xs rounded-full transition-colors disabled:opacity-50 ${
                  template === opt.id
                    ? "bg-indigo-600 text-white font-medium shadow-2xs"
                    : "text-zinc-600 hover:text-zinc-900"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {isGenerating && (
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-white/80 backdrop-blur-sm z-10">
              <RefreshCw className="h-10 w-10 text-emerald-600 animate-spin mb-4" />
              <p className="text-zinc-700 font-medium">正在通过无头浏览器渲染排版...</p>
              <p className="text-zinc-500 text-sm mt-2">首次渲染可能需要较长时间加载字体</p>
            </div>
          )}
          
          {error && (
            <div className="absolute inset-0 flex items-center justify-center bg-white z-10 p-8 text-center">
              <div>
                <p className="text-red-500 font-medium mb-2">预览生成失败</p>
                <p className="text-zinc-500 text-sm">{error}</p>
              </div>
            </div>
          )}

          {pdfUrl && !isGenerating && !error && (
            <iframe 
              src={`${pdfUrl}#toolbar=0&navpanes=0&scrollbar=0`}
              className="w-full h-full border-none"
              title="PDF Preview"
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
