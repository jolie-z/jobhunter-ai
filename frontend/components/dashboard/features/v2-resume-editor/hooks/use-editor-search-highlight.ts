"use client"

import { useEffect, useRef, useCallback, useState } from "react"

export interface SearchMatchItem {
  id: string
  type: "text" | "input"
  range?: Range
  element?: HTMLInputElement | HTMLTextAreaElement
  text: string
  charIndex: number
}

interface UseEditorSearchHighlightProps {
  findText: string
  currentMatchIndex: number
  canvasSelector?: string
}

function clearInputHighlightClasses(container: Element | null) {
  if (!container) return
  container
    .querySelectorAll(".search-match-input-active, .search-match-input-inactive")
    .forEach((el) => {
      el.classList.remove("search-match-input-active", "search-match-input-inactive")
    })
}

/**
 * 🌟 简历编辑器全画布双轨高亮与精准光标导航 Hook
 * 1. 采用浏览器原生标准 CSS Custom Highlight API (CSS.highlights) 实现零 DOM 篡改的富文本高亮
 * 2. 区分非激活项 (黄底) 与激活项 (橙底白字光标)，精准居中平滑滚动
 * 3. 针对表单控件通过原生 class 外框进行非侵入式聚焦指示，防范样式竞争
 * 4. 解耦全量 DOM 文本扫描与活动光标切换，保证高性能无闪烁导航
 */
export function useEditorSearchHighlight({
  findText,
  currentMatchIndex,
  canvasSelector = '[data-resume-canvas="true"]',
}: UseEditorSearchHighlightProps) {
  const matchesRef = useRef<SearchMatchItem[]>([])
  const [matches, setMatches] = useState<SearchMatchItem[]>([])
  const activeBeaconTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const activeBeaconElRef = useRef<HTMLElement | null>(null)

  // 判断当前浏览器是否支持 CSS Custom Highlight API
  const isHighlightSupported =
    typeof window !== "undefined" &&
    typeof CSS !== "undefined" &&
    "highlights" in CSS &&
    typeof (window as any).Highlight !== "undefined"

  // 彻底清除上一个呼吸信标样式与定时器（避免误删元素自身原有的圆角类）
  const clearActiveBeacon = useCallback(() => {
    if (activeBeaconTimeoutRef.current) {
      clearTimeout(activeBeaconTimeoutRef.current)
      activeBeaconTimeoutRef.current = null
    }
    if (activeBeaconElRef.current) {
      activeBeaconElRef.current.classList.remove("ring-2", "ring-orange-500/80", "ring-offset-2")
      activeBeaconElRef.current = null
    }
  }, [])

  // 清除全局高亮与输入框外框样式
  const clearHighlights = useCallback(() => {
    clearActiveBeacon()

    if (isHighlightSupported) {
      try {
        ;(CSS as any).highlights.delete("search-results")
        ;(CSS as any).highlights.delete("search-result-active")
      } catch (err) {
        console.warn("[SearchHighlight] Failed to delete CSS highlights:", err)
      }
    }

    const container = document.querySelector(canvasSelector)
    clearInputHighlightClasses(container)

    matchesRef.current = []
    setMatches([])
  }, [isHighlightSupported, canvasSelector, clearActiveBeacon])

  // 仅更新活动项的高亮与表单激活类（O(1) 高效切换，无闪烁）
  const applyActiveHighlight = useCallback(
    (targetIndex: number, currentMatches: SearchMatchItem[] = matchesRef.current) => {
      if (!currentMatches.length) return

      const safeIdx = Math.max(0, Math.min(targetIndex, currentMatches.length - 1))
      const container = document.querySelector(canvasSelector)

      // 1. 注册非激活与当前激活项到 CSS.highlights
      if (isHighlightSupported) {
        try {
          const inactiveRanges: Range[] = []
          let activeRange: Range | null = null

          currentMatches.forEach((m, idx) => {
            if (m.type === "text" && m.range) {
              if (idx === safeIdx) {
                activeRange = m.range
              } else {
                inactiveRanges.push(m.range)
              }
            }
          })

          // 防御极限超大匹配量场景：优先使用标准 Highlight.add(range) 迭代添加；若运行环境为精简 Mock 则回退至构造入参
          let inactiveHighlight: any
          try {
            const candidate = new (window as any).Highlight()
            if (typeof candidate.add === "function") {
              inactiveRanges.forEach((r) => candidate.add(r))
              inactiveHighlight = candidate
            } else {
              inactiveHighlight = new (window as any).Highlight(...inactiveRanges)
            }
          } catch {
            inactiveHighlight = new (window as any).Highlight(...inactiveRanges)
          }
          ;(CSS as any).highlights.set("search-results", inactiveHighlight)

          if (activeRange) {
            const activeHighlight = new (window as any).Highlight(activeRange)
            ;(CSS as any).highlights.set("search-result-active", activeHighlight)
          } else {
            ;(CSS as any).highlights.delete("search-result-active")
          }
        } catch (err) {
          console.warn("[SearchHighlight] Error setting CSS highlights:", err)
        }
      }

      // 2. 更新表单输入框的高亮类名（按 DOM 引用去重，消除 active 与 inactive 冲突）
      clearInputHighlightClasses(container)

      const activeMatch = currentMatches[safeIdx]
      const activeFormEl = activeMatch?.type === "input" ? activeMatch.element : null

      const matchedElements = new Set<HTMLInputElement | HTMLTextAreaElement>()
      currentMatches.forEach((m) => {
        if (m.type === "input" && m.element) {
          matchedElements.add(m.element)
        }
      })

      matchedElements.forEach((el) => {
        if (el === activeFormEl) {
          el.classList.add("search-match-input-active")
        } else {
          el.classList.add("search-match-input-inactive")
        }
      })
    },
    [canvasSelector, isHighlightSupported]
  )

  // 执行全画布扫描并构建匹配列表（仅在检索词或画布变化时触发）
  const scanMatches = useCallback(() => {
    const trimmed = findText.trim()
    if (!trimmed) {
      clearHighlights()
      return []
    }

    const container = document.querySelector(canvasSelector)
    if (!container) {
      clearHighlights()
      console.warn(`[useEditorSearchHighlight] 未找到画布容器: ${canvasSelector}`)
      return []
    }

    const query = trimmed.toLowerCase()
    const allMatches: SearchMatchItem[] = []

    // 1. 扫描画布内所有可见文本节点 (TreeWalker 过滤按钮、导航与 textarea 文本)
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement
        if (!parent) return NodeFilter.FILTER_REJECT
        const tag = parent.tagName.toLowerCase()
        if (["button", "script", "style", "svg", "textarea"].includes(tag)) {
          return NodeFilter.FILTER_REJECT
        }
        if (parent.closest("button") || parent.closest("[role='menu']") || parent.closest("textarea")) {
          return NodeFilter.FILTER_REJECT
        }
        return NodeFilter.FILTER_ACCEPT
      },
    })

    let currentNode = walker.nextNode()
    let textMatchCount = 0
    while (currentNode) {
      const text = currentNode.nodeValue || ""
      const lower = text.toLowerCase()
      let pos = lower.indexOf(query)
      while (pos !== -1) {
        try {
          const range = document.createRange()
          range.setStart(currentNode, pos)
          range.setEnd(currentNode, pos + query.length)

          allMatches.push({
            id: `text-match-${textMatchCount++}`,
            type: "text",
            range,
            text: text.substring(pos, pos + query.length),
            charIndex: pos,
          })
        } catch {
          // 容错处理
        }
        pos = lower.indexOf(query, pos + query.length)
      }
      currentNode = walker.nextNode()
    }

    // 2. 扫描所有表单输入控件 (涵盖 text/email/tel/url 及 textarea)
    const inputs = container.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(
      'input:is([type="text"], [type="email"], [type="tel"], [type="url"], :not([type])):not([data-search-ignore="true"]), textarea:not([data-search-ignore="true"])'
    )
    inputs.forEach((inputEl, idx) => {
      const val = inputEl.value || ""
      const lower = val.toLowerCase()
      let pos = lower.indexOf(query)
      while (pos !== -1) {
        allMatches.push({
          id: `input-match-${idx}-${pos}`,
          type: "input",
          element: inputEl,
          text: val.substring(pos, pos + query.length),
          charIndex: pos,
        })
        pos = lower.indexOf(query, pos + query.length)
      }
    })

    // 3. 若无任何匹配项，彻底清理旧高亮与样式，防范无命中时旧样式残留冻结
    if (allMatches.length === 0) {
      clearHighlights()
      return []
    }

    // 4. 严格按 DOM 拓扑先后次序全局排序
    allMatches.sort((a, b) => {
      const nodeA = a.type === "text" ? a.range!.startContainer : a.element!
      const nodeB = b.type === "text" ? b.range!.startContainer : b.element!
      if (nodeA === nodeB) {
        return a.charIndex - b.charIndex
      }
      const position = nodeA.compareDocumentPosition(nodeB)
      if (position & Node.DOCUMENT_POSITION_FOLLOWING) return -1
      if (position & Node.DOCUMENT_POSITION_PRECEDING) return 1
      return 0
    })

    matchesRef.current = allMatches
    setMatches(allMatches)
    return allMatches
  }, [findText, clearHighlights, canvasSelector])

  // 平滑滚动定位到当前命中项，并附加呼吸视觉光标（返回是否精准命中）
  const scrollToCurrentMatch = useCallback(
    (targetIndex: number): boolean => {
      // 无论目标是文本还是表单输入框，优先清除先前的呼吸信标
      clearActiveBeacon()

      const currentMatches = matchesRef.current
      if (!currentMatches.length || targetIndex < 0 || targetIndex >= currentMatches.length) {
        return false
      }
      const current = currentMatches[targetIndex]

      if (current.type === "text" && current.range) {
        const parentEl = current.range.startContainer.parentElement
        if (parentEl) {
          parentEl.scrollIntoView({ behavior: "smooth", block: "center" })

          // 呈现 1.5s 柔和呼吸信标框
          parentEl.classList.add("ring-2", "ring-orange-500/80", "ring-offset-2")
          activeBeaconElRef.current = parentEl
          activeBeaconTimeoutRef.current = setTimeout(() => {
            parentEl.classList.remove("ring-2", "ring-orange-500/80", "ring-offset-2")
            activeBeaconElRef.current = null
          }, 1500)
          return true
        }
      } else if (current.type === "input" && current.element) {
        current.element.scrollIntoView({ behavior: "smooth", block: "center" })
        return true
      }
      return false
    },
    [clearActiveBeacon]
  )

  // 1. 当 findText 或 canvas 变动时，执行全量扫描并应用当前高亮（无匹配时显式清理）
  useEffect(() => {
    const scanned = scanMatches()
    if (scanned.length > 0) {
      applyActiveHighlight(0, scanned)
    } else {
      clearHighlights()
    }
  }, [scanMatches]) // eslint-disable-line react-hooks/exhaustive-deps

  // 2. 当仅 currentMatchIndex 变动时，仅做轻量 O(1) 活动光标样式切换（解耦全量 TreeWalker 遍历）
  useEffect(() => {
    if (matchesRef.current.length > 0) {
      applyActiveHighlight(currentMatchIndex, matchesRef.current)
    }
  }, [currentMatchIndex, applyActiveHighlight])

  // 3. 组件卸载或清空查找词时做全局清理
  useEffect(() => {
    return () => {
      clearHighlights()
    }
  }, [clearHighlights])

  return {
    matches,
    scrollToCurrentMatch,
    totalMatches: matches.length,
    clearHighlights,
  }
}
