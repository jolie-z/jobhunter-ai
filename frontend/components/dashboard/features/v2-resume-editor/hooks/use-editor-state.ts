import { API_BASE } from "@/lib/api"
import { useState, useEffect } from "react"
import { toast } from "@/hooks/use-toast"

export function useEditorState() {
  const [previewOpen, setPreviewOpen] = useState(false)
  
  // 模块内工具栏弹窗状态
  const [compressOpen, setCompressOpen] = useState(false)
  const [pruneOpen, setPruneOpen] = useState(false)
  const [trashOpen, setTrashOpen] = useState(false)
  const [workRestoreOpen, setWorkRestoreOpen] = useState(false)
  const [workInitialDraftOpen, setWorkInitialDraftOpen] = useState(false)
  const [projectInitialDraftOpen, setProjectInitialDraftOpen] = useState(false)

  // 查找与替换状态
  const [findText, setFindText] = useState("")
  const [replaceText, setReplaceText] = useState("")
  const [totalMatches, setTotalMatches] = useState(0)
  const [currentMatchIndex, setCurrentMatchIndex] = useState(0)

  // 格式化状态
  const [activeSyncModuleId, setActiveSyncModuleId] = useState<string | null>(null)
  const [formattingModuleId, setFormattingModuleId] = useState<string | null>(null)

  useEffect(() => {
      }, [])

  const handleFormatMarkdown = async (id: string, title: string, content: string, onChange: (val: string) => void) => {
    if (!content.trim()) return
    setFormattingModuleId(id)
    try {
      const res = await fetch(`${API_BASE}/api/strategy/format_markdown`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ module_title: title, current_content: content })
      })
      const data = await res.json()
      if (data.status === "success" && data.data?.formatted_content) {
        onChange(data.data.formatted_content)
      } else {
        toast({ variant: "destructive", title: "❌ 自动排版失败", description: data.message || "后端排版接口返回异常" })
      }
    } catch (e) {
      console.error("Format markdown failed:", e)
      toast({ variant: "destructive", title: "❌ 自动排版失败", description: "网络请求异常，请检查后端服务" })
    } finally {
      setFormattingModuleId(null)
    }
  }

  return {
    state: {
      previewOpen,
            compressOpen,
      pruneOpen,
      trashOpen,
      workRestoreOpen,
      workInitialDraftOpen,
      projectInitialDraftOpen,
      findText,
      replaceText,
      totalMatches,
      currentMatchIndex,
      activeSyncModuleId,
      formattingModuleId
    },
    actions: {
      setPreviewOpen,
            setCompressOpen,
      setPruneOpen,
      setTrashOpen,
      setWorkRestoreOpen,
      setWorkInitialDraftOpen,
      setProjectInitialDraftOpen,
      setFindText,
      setReplaceText,
      setTotalMatches,
      setCurrentMatchIndex,
      setActiveSyncModuleId,
      setFormattingModuleId,
      handleFormatMarkdown
    }
  }
}
