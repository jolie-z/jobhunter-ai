"use client"

// 简历正文编辑器：所见即所得（WYSIWYG）。
// 点击渲染区进入编辑后直接呈现加粗/列表/表格等最终效果，不再裸露 **、# 等
// Markdown 标记（不要求用户懂 Markdown）；底层契约不变——进出的仍是 markdown
// 纯文本，保存/导出/AI 改写链路零改动。
// 高级用户可用工具栏「编辑模式」切到 IR/分屏源码；vditor 加载失败自动回退纯
// Textarea 源码编辑，保证任何时候都能改内容。

import React, { useEffect, useRef, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import type Vditor from "vditor"
import "vditor/dist/index.css"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

interface MarkdownEditorProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  className?: string
  minHeight?: string
}

// vditor JS 体积较大（~1MB）按需动态加载、全页共享一次（样式 import 是纯 CSS，
// 由 Next 构建期抽取、不进 JS 主包，两者不矛盾）；SSR 下绝不触碰 window。
// 加载失败时清空缓存 promise，下次进入编辑可重试（避免一次抖动就永久降级源码框）。
let vditorLoader: Promise<typeof import("vditor")["default"]> | null = null
function loadVditor(): Promise<typeof import("vditor")["default"]> {
  if (!vditorLoader) {
    vditorLoader = import("vditor").then((m) => m.default).catch((e) => {
      vditorLoader = null
      throw e
    })
  }
  return vditorLoader
}

const RME_TOOLBAR = [
  "undo", "redo", "|",
  "headings", "bold", "italic", "strike", "|",
  "list", "ordered-list", "check", "outdent", "indent", "|",
  "quote", "code", "inline-code", "link", "table", "|",
  "edit-mode",
]

// 贴合卡片内联编辑观感的样式注入（每页一次），颜色走 shadcn 变量以适配明暗主题
const RME_STYLE_ID = "rme-vditor-style"
const RME_CSS = `
.rme-vditor .vditor {
  --border-color: var(--border);
  --toolbar-background: transparent;
  --toolbar-icon-color: var(--muted-foreground);
  --toolbar-icon-hover-color: var(--foreground);
  --panel-background: var(--popover);
  --panel-border: 1px solid var(--border);
  --textarea-background-color: transparent;
  --textarea-text-color: var(--foreground);
  border: none;
  background: transparent;
  min-height: inherit;
  display: flex;
  flex-direction: column;
}
.rme-vditor .vditor-toolbar { padding: 0 2px; flex-wrap: wrap; }
.rme-vditor .vditor-toolbar svg { width: 14px; height: 14px; }
.rme-vditor .vditor-wysiwyg { background: transparent; min-height: inherit; }
.rme-vditor .vditor-reset {
  font-family: inherit;
  /* 与阅读态 prose-sm（14px/1.7）对齐，编辑/阅读两态字号行高一致才算「所见即所得」 */
  font-size: 14px;
  line-height: 1.7;
  color: var(--foreground);
  padding: 8px 12px 12px;
}
.rme-vditor .vditor-reset p { margin: 0.3em 0; }
.rme-vditor .vditor-reset li > p { margin: 0; }
.rme-vditor .vditor-reset h1,
.rme-vditor .vditor-reset h2,
.rme-vditor .vditor-reset h3,
.rme-vditor .vditor-reset h4,
.rme-vditor .vditor-reset h5,
.rme-vditor .vditor-reset h6 { margin: 0.7em 0 0.3em; font-weight: 600; }
.rme-vditor .vditor-reset h1 { font-size: 1.3em; }
.rme-vditor .vditor-reset h2 { font-size: 1.18em; }
.rme-vditor .vditor-reset h3 { font-size: 1.08em; }
.rme-vditor .vditor-reset h4,
.rme-vditor .vditor-reset h5,
.rme-vditor .vditor-reset h6 { font-size: 1em; }
.rme-vditor .vditor-reset ul,
.rme-vditor .vditor-reset ol { margin: 0.3em 0; padding-left: 1.5em; }
.rme-vditor .vditor-reset li { margin: 0.15em 0; }
.rme-vditor .vditor-reset blockquote {
  margin: 0.5em 0;
  padding: 0.2em 0.9em;
  border-left: 3px solid var(--border);
  color: var(--muted-foreground);
}
.rme-vditor .vditor-reset a { color: var(--primary); text-decoration: underline; }
.rme-vditor .vditor-reset code { font-size: 0.9em; }
.rme-vditor .vditor-reset table { font-size: 12px; }
.rme-vditor .vditor-reset img { max-width: 100%; }
`

function injectRmeStyle() {
  if (typeof document === "undefined" || document.getElementById(RME_STYLE_ID)) return
  const tag = document.createElement("style")
  tag.id = RME_STYLE_ID
  tag.textContent = RME_CSS
  document.head.appendChild(tag)
}

export function MarkdownEditor({ value, onChange, placeholder, className, minHeight = "min-h-[120px]" }: MarkdownEditorProps) {
  const [isEditing, setIsEditing] = useState(false)

  if (!isEditing) {
    return (
      <div
        onClick={() => setIsEditing(true)}
        className={cn(
          minHeight,
          "cursor-text rounded-md border border-transparent hover:border-border/50 hover:bg-secondary/10 p-3 text-[13px] leading-relaxed transition-colors",
          className
        )}
      >
        {value ? (
          <div className="prose prose-sm dark:prose-invert max-w-none prose-p:my-1 prose-ul:my-1 prose-li:my-0.5">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown>
          </div>
        ) : (
          <span className="text-muted-foreground">{placeholder || "点击此处添加描述..."}</span>
        )}
      </div>
    )
  }

  return (
    <WysiwygSurface
      value={value}
      onChange={onChange}
      onExit={() => setIsEditing(false)}
      placeholder={placeholder}
      className={className}
      minHeight={minHeight}
    />
  )
}

type WysiwygSurfaceProps = {
  value: string
  onChange: (value: string) => void
  onExit: () => void
  placeholder?: string
  className?: string
  minHeight: string
}

function WysiwygSurface({ value, onChange, onExit, placeholder, className, minHeight }: WysiwygSurfaceProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const instanceRef = useRef<Vditor | null>(null)
  const disposedRef = useRef(false)
  const lastEmittedRef = useRef(value)
  const commitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const exitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)
  const readyRef = useRef(false)
  const failedRef = useRef(false)

  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange
  const onExitRef = useRef(onExit)
  onExitRef.current = onExit

  // 把编辑器当前内容冲进 onChange（去重：内容没变不触发父级重渲染）。
  // 双重短路：回退 Textarea 后不再读旧 vditor 实例；实例未 ready（after 未回调）
  // 时 getValue 可能返回空串，冲刷会把父级正文清成空——绝不在半初始化态 emit
  const commitNow = () => {
    if (failedRef.current || !readyRef.current) return
    if (commitTimerRef.current) {
      clearTimeout(commitTimerRef.current)
      commitTimerRef.current = null
    }
    const vd = instanceRef.current
    if (!vd) return
    const md = vd.getValue()
    if (typeof md === "string" && md !== lastEmittedRef.current) {
      lastEmittedRef.current = md
      onChangeRef.current(md)
    }
  }

  const scheduleCommit = () => {
    if (commitTimerRef.current) clearTimeout(commitTimerRef.current)
    commitTimerRef.current = setTimeout(() => {
      commitTimerRef.current = null
      commitNow()
    }, 300)
  }

  // 失焦延迟退出：点工具栏/下拉时 focus 未必立刻回来，靠容器内 pointerdown/focusin 取消
  const scheduleExit = () => {
    if (exitTimerRef.current) clearTimeout(exitTimerRef.current)
    exitTimerRef.current = setTimeout(() => {
      exitTimerRef.current = null
      commitNow()
      onExitRef.current()
    }, 200)
  }
  const cancelExit = () => {
    if (exitTimerRef.current) {
      clearTimeout(exitTimerRef.current)
      exitTimerRef.current = null
    }
  }

  // 初始化 Vditor（客户端 only）
  useEffect(() => {
    disposedRef.current = false
    injectRmeStyle()
  // 兜底：vditor 异步初始化迟迟不完成（chunk 加载失败/内部卡死）时回退 Textarea，绝不把用户挡死。
  // 回退前必须销毁半初始化实例并置 failed 短路——否则外部 pointerdown 会经 commitNow()
  // 读到旧实例的陈旧内容，覆盖用户已在回退 Textarea 里输入的文字
  const initTimeout = setTimeout(() => {
    if (!disposedRef.current && !readyRef.current) {
      console.warn("[MarkdownEditor] vditor 初始化超时，回退源码编辑")
      try {
        commitNow()
      } catch {
        // 半初始化实例不可用则忽略
      }
      try {
        instanceRef.current?.destroy()
      } catch {
        // 已销毁则忽略
      }
      instanceRef.current = null
      failedRef.current = true
      setFailed(true)
    }
  }, 8000)
    let instance: Vditor | null = null
    ;(async () => {
      try {
        const VditorCtor = await loadVditor()
        // disposed：组件已卸载；failed：8s 超时兜底已回退 Textarea——两者都不得再建实例
        if (disposedRef.current || failedRef.current || !hostRef.current) return
        const isDark = document.documentElement.classList.contains("dark")
        instance = new VditorCtor(hostRef.current, {
          lang: "zh_CN",
          theme: isDark ? "dark" : "classic",
          icon: "ant",
          mode: "wysiwyg",
          // 自托管 vditor 运行时资源（public/vditor/，含核心解析器 lute 与工具栏图标）：
          // 默认 jsdelivr CDN 在国内网络不稳定，lute 拉不到编辑器就起不来
          cdn: "/vditor",
          value: lastEmittedRef.current,
          placeholder: placeholder || "",
          cache: { enable: false },
          undoDelay: 200,
          toolbar: RME_TOOLBAR,
          upload: {
            // 简历正文不收文件/图片：拦截上传与粘贴图片，避免 blob:url 垃圾写进 markdown。
            // vditor 4 源码：handler 存在即完全接管上传路径，返回 string 会以提示条展示，
            // 非 string（null 等）静默终止（dist/index.js:6204-6215）；返回提示串让用户知道为何没插进去
            handler: () => "简历正文不支持插入图片/文件",
          },
          focus: () => cancelExit(),
          blur: () => scheduleExit(),
          input: () => scheduleCommit(),
          esc: () => {
            commitNow()
            onExitRef.current()
          },
          after: () => {
            if (disposedRef.current) return
            clearTimeout(initTimeout)
            readyRef.current = true
            setReady(true)
            try {
              instance?.focus()
            } catch {
              // 聚焦失败不影响编辑
            }
          },
        })
        instanceRef.current = instance
      } catch (e) {
        console.warn("[MarkdownEditor] WYSIWYG 编辑器加载失败，回退源码编辑", e)
        if (!disposedRef.current) setFailed(true)
      }
    })()

    return () => {
      disposedRef.current = true
      clearTimeout(initTimeout)
      // 未及落盘的输入先冲一遍 onChange，防快速切换/卸载丢最后几百毫秒的编辑
      try {
        commitNow()
      } catch {
        // 实例已不可用则忽略
      }
      if (exitTimerRef.current) clearTimeout(exitTimerRef.current)
      try {
        instanceRef.current?.destroy()
      } catch {
        // 已销毁则忽略
      }
      instanceRef.current = null
    }
    // 仅挂载时初始化一次；value/onChange 走 ref 与同步 effect
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 外部值同步：AI 改写/自动排版在非聚焦态更新内容时灌进编辑器；聚焦中不动防光标跳
  useEffect(() => {
    const vd = instanceRef.current
    if (!vd || !ready) return
    const host = hostRef.current
    if (host && document.activeElement instanceof Node && host.contains(document.activeElement)) return
    if (value !== lastEmittedRef.current) {
      lastEmittedRef.current = value
      try {
        vd.setValue(value)
      } catch {
        // 实例销毁中的竞态，忽略
      }
    }
  }, [value, ready])

  // 容器内的指针按下/焦点进入视为「还在编辑」取消失焦退出；容器外的指针按下
  // （保存按钮/切换模块等）先同步冲刷未落盘输入——否则外部 onClick（如 handleSave）
  // 会先于 200ms 延迟提交执行，父级拿到旧 value 丢尾部输入
  useEffect(() => {
    const onDocPointerDown = (e: PointerEvent) => {
      if (hostRef.current?.contains(e.target as Node)) {
        cancelExit()
      } else {
        commitNow()
      }
    }
    const onDocFocusIn = (e: FocusEvent) => {
      if (hostRef.current?.contains(e.target as Node)) cancelExit()
    }
    document.addEventListener("pointerdown", onDocPointerDown, true)
    document.addEventListener("focusin", onDocFocusIn)
    return () => {
      document.removeEventListener("pointerdown", onDocPointerDown, true)
      document.removeEventListener("focusin", onDocFocusIn)
    }
  }, [])

  if (failed) {
    return (
      <Textarea
        autoFocus
        defaultValue={value}
        onChange={(e) => {
          lastEmittedRef.current = e.target.value
          onChangeRef.current(e.target.value)
        }}
        onBlur={() => onExitRef.current()}
        placeholder={placeholder}
        className={cn(minHeight, "resize-y bg-secondary/30 text-[13px] leading-relaxed font-mono", className)}
      />
    )
  }

  return (
    <div className={cn("rme-vditor relative rounded-md border border-border/60 bg-secondary/20", minHeight, className)}>
      <div ref={hostRef} style={{ minHeight: "inherit" }} className="overflow-hidden rounded-md" />
      {!ready && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-background/60 text-xs text-muted-foreground">
          编辑器加载中…
        </div>
      )}
    </div>
  )
}
