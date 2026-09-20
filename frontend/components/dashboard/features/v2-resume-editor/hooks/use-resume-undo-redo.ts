"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import type { ResumeDataV2 } from "@/types/resume"

export interface UseResumeUndoRedoOptions {
  resumeKey?: string
  maxHistory?: number
  debounceMs?: number
  /**
   * 模式选择：
   * - 'auto': 生产环境默认，依赖真实物理交互门禁（仅用户打字/点击触发的修改计入撤销，背景水合静默同步）
   * - 'always-record': 测试或离散录制模式，所有 store 变动均视作操作
   */
  mode?: "auto" | "always-record"
}

// 用户物理交互时间窗口阈值：
// 真实用户打字、点击与输入到 React 合成事件/store 写入之间的最大时延兜底（1.5s）
const USER_INTERACTION_WINDOW_MS = 1500

// 物理交互门禁监听的关键原生 DOM 事件列表（捕获阶段拦截，先于 React 合成事件）
const GATED_INTERACTION_EVENTS: Array<keyof WindowEventMap> = [
  "input",
  "change",
  "compositionstart",
  "compositionend",
  "paste",
  "drop",
  "click",
  "pointerdown",
]

function cloneResume(data: ResumeDataV2 | null): ResumeDataV2 | null {
  if (!data) return null
  return JSON.parse(JSON.stringify(data))
}

function isContentEqual(a: ResumeDataV2 | null, b: ResumeDataV2 | null): boolean {
  if (a === b) return true
  if (!a || !b) return false
  return JSON.stringify(a) === JSON.stringify(b)
}

/**
 * 🌟 简历编辑器全画布撤销与重做 (Undo / Redo) 高内聚历史栈 Hook
 * 1. 严格对齐 Excel 撤销与重做流转规范：
 *    - 默认就绪态：双灰（canUndo: false, canRedo: false）
 *    - 识别修改态：仅用户真实输入点亮撤销（canUndo: true, canRedo: false）
 *    - 撤销到底态：回退至初始状态后撤销变灰，重做点亮（canUndo: false, canRedo: true）
 *    - 重做到底态：重做用完后重做变灰，撤销再次点亮（canUndo: true, canRedo: false）
 *    - 新输入清空：撤销状态下用户一旦键入新内容，重做栈立刻清空
 *    - 净零自愈：用户打字后删回原样，防抖到期自动回灰
 * 2. 物理交互门禁 (User Interaction Sensor)：
 *    - 捕获真实 DOM 事件 (input / composition / paste / drop / click / pointerdown)
 *    - 彻底拦截后台异步拉取（如母本头像、策略配置、初始化水合）对撤销栈的虚假污染
 * 3. 栈顶深比较去重守卫 (De-duplication Guard)，彻底杜绝撤销“空步”与幻影节点
 * 4. 智能防抖合并 (800ms) + 离散动作即时定格 (takeSnapshot)
 * 5. 跨简历异步加载重置机制，彻底杜绝跨文档数据穿透污染
 * 6. 跨平台快捷键监听 (⌘Z / ⌘⇧Z / Ctrl+Y) 与原生输入控件分流避让
 * 7. 三位一体生命周期彻底清理 (unsubscribe + timer + DOM event listeners)
 */
export function useResumeUndoRedo(options: UseResumeUndoRedoOptions = {}) {
  const { resumeKey, maxHistory = 30, debounceMs = 800, mode = "auto" } = options

  const pastRef = useRef<ResumeDataV2[]>([])
  const futureRef = useRef<ResumeDataV2[]>([])
  const lastCommittedRef = useRef<ResumeDataV2 | null>(null)
  const isInitializedRef = useRef(false)
  if (!isInitializedRef.current) {
    isInitializedRef.current = true
    lastCommittedRef.current = cloneResume(useResumeV2Store.getState().resumeData)
  }

  const prevResumeKeyRef = useRef(resumeKey)
  const debounceTimerRef = useRef<NodeJS.Timeout | null>(null)
  const skipNextSnapshotRef = useRef(false)
  const hasPendingUserEditRef = useRef(false)
  const lastUserInteractionTimeRef = useRef<number>(0)

  const [canUndo, setCanUndo] = useState(false)
  const [canRedo, setCanRedo] = useState(false)

  // 状态同步（严格对齐 Excel 充要条件：有历史栈 或 存在已确认的用户未落盘打字）
  const updateCanUndoRedo = useCallback(() => {
    setCanUndo(pastRef.current.length > 0 || hasPendingUserEditRef.current)
    setCanRedo(futureRef.current.length > 0)
  }, [])

  // 安全压入 past 栈（带栈顶去重与 FIFO 深度限制）
  const pushToPast = useCallback(
    (snapshot: ResumeDataV2) => {
      const snapStr = JSON.stringify(snapshot)
      if (pastRef.current.length > 0) {
        const topStr = JSON.stringify(pastRef.current[pastRef.current.length - 1])
        if (topStr === snapStr) {
          return
        }
      }
      pastRef.current.push(JSON.parse(snapStr))
      if (pastRef.current.length > maxHistory) {
        pastRef.current.shift()
      }
    },
    [maxHistory]
  )

  // 离散关键动作立即定格快照（支持显式传入操作前的基准数据）
  const takeSnapshot = useCallback(
    (explicitSnapshot?: ResumeDataV2 | null) => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current)
        debounceTimerRef.current = null
      }
      hasPendingUserEditRef.current = false

      const targetSnapshot = explicitSnapshot || lastCommittedRef.current || useResumeV2Store.getState().resumeData
      if (!targetSnapshot) return

      pushToPast(targetSnapshot)
      futureRef.current = [] // 新的实质性编辑分支清空重做栈
      lastCommittedRef.current = cloneResume(targetSnapshot)
      updateCanUndoRedo()
    },
    [pushToPast, updateCanUndoRedo]
  )

  // 执行撤销 (Undo)
  const undo = useCallback(() => {
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current)
      debounceTimerRef.current = null
    }

    const currentLive = useResumeV2Store.getState().resumeData
    if (!currentLive) return

    // 1. 若当前存在打字中但尚未到期的未落盘增量
    if (
      hasPendingUserEditRef.current &&
      lastCommittedRef.current &&
      !isContentEqual(currentLive, lastCommittedRef.current)
    ) {
      // 将当前屏幕所见的打字内容转存入 future，保证重做可恢复
      futureRef.current.push(cloneResume(currentLive)!)
      if (futureRef.current.length > maxHistory) {
        futureRef.current.shift()
      }

      // 回滚到打字前的基准数据
      const previous = cloneResume(lastCommittedRef.current)!
      hasPendingUserEditRef.current = false

      // 关键防幻影守卫：弹出与回滚目标内容相同的冗余栈顶（如 takeSnapshot 预存的基准快照），
      // 避免出现当前已回滚至 previous、past 栈顶依然残留 previous 导致撤销无法变灰的缺陷
      while (
        pastRef.current.length > 0 &&
        isContentEqual(pastRef.current[pastRef.current.length - 1], previous)
      ) {
        pastRef.current.pop()
      }

      skipNextSnapshotRef.current = true
      useResumeV2Store.getState().setResumeData(previous)
      lastCommittedRef.current = cloneResume(previous)

      updateCanUndoRedo()
      return
    }

    hasPendingUserEditRef.current = false

    // 2. 若依然无历史可退，则无法撤销
    if (pastRef.current.length === 0) {
      updateCanUndoRedo()
      return
    }

    // 3. 将屏幕上可见的最新实时状态转存入 future
    futureRef.current.push(cloneResume(currentLive)!)
    if (futureRef.current.length > maxHistory) {
      futureRef.current.shift()
    }

    // 4. 弹出上一历史快照
    const previous = pastRef.current.pop()!

    // 安全弹出连续重复的相同历史节点
    while (
      pastRef.current.length > 0 &&
      isContentEqual(pastRef.current[pastRef.current.length - 1], previous)
    ) {
      pastRef.current.pop()
    }

    // 5. 同步置锁并恢复 store
    skipNextSnapshotRef.current = true
    useResumeV2Store.getState().setResumeData(previous)
    lastCommittedRef.current = cloneResume(previous)

    updateCanUndoRedo()
  }, [maxHistory, updateCanUndoRedo])

  // 执行重做 (Redo)
  const redo = useCallback(() => {
    // 判空前置保护：若重做栈为空，直接安全早退，绝不误杀在飞的用户打字防抖与 pending 状态
    if (futureRef.current.length === 0) {
      updateCanUndoRedo()
      return
    }

    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current)
      debounceTimerRef.current = null
    }
    hasPendingUserEditRef.current = false

    const currentLive = useResumeV2Store.getState().resumeData
    if (!currentLive) return

    // 1. 将当前实时状态压入 past 栈
    pushToPast(currentLive)

    // 2. 弹出将要重做的下一个快照
    const next = futureRef.current.pop()!

    // 3. 同步置锁并恢复 store
    skipNextSnapshotRef.current = true
    useResumeV2Store.getState().setResumeData(next)
    lastCommittedRef.current = cloneResume(next)

    updateCanUndoRedo()
  }, [pushToPast, updateCanUndoRedo])

  // 跨简历切换：仅在 resumeKey 实际变动时，清空历史栈并重置锚定
  useEffect(() => {
    if (prevResumeKeyRef.current !== resumeKey) {
      prevResumeKeyRef.current = resumeKey
      pastRef.current = []
      futureRef.current = []
      hasPendingUserEditRef.current = false
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current)
        debounceTimerRef.current = null
      }
      lastCommittedRef.current = null
      updateCanUndoRedo()
    }
  }, [resumeKey, updateCanUndoRedo])

  // 核心订阅与生命周期管理
  useEffect(() => {
    // 1. 物理交互门禁监听器
    const markUserInteraction = () => {
      lastUserInteractionTimeRef.current = Date.now()
    }

    for (const eventName of GATED_INTERACTION_EVENTS) {
      window.addEventListener(eventName, markUserInteraction, true)
    }

    // 2. 订阅 Zustand store
    const unsubscribe = useResumeV2Store.subscribe((state) => {
      // 若处于 undo/redo 同步置锁期间，一次性原子消费并跳过本次监听
      if (skipNextSnapshotRef.current) {
        skipNextSnapshotRef.current = false
        return
      }

      const nextData = state.resumeData
      if (!nextData) return

      // 初次挂载或跨简历切换后 lastCommittedRef 为空，以新数据为干净初始基准，绝对双灰
      if (!lastCommittedRef.current) {
        lastCommittedRef.current = cloneResume(nextData)
        hasPendingUserEditRef.current = false
        updateCanUndoRedo()
        return
      }

      // 等值空触发守卫：若新数据与当前已确立的基准深度一致，说明内容未产生实质变更
      // 绝不视作新编辑分支，绝不摧毁 future 重做栈，保持当前状态原样早退
      if (isContentEqual(nextData, lastCommittedRef.current)) {
        updateCanUndoRedo()
        return
      }

      // 判定本次 store 变更是否属于“用户物理交互引发”
      const isUserAction =
        mode === "always-record" ||
        Date.now() - lastUserInteractionTimeRef.current < USER_INTERACTION_WINDOW_MS ||
        hasPendingUserEditRef.current

      // 若非用户交互引发（例如后台拉取母本头像、切岗加载、策略异步水合）：
      // 视为静默基准同步，绝不压栈，绝不启动防抖，绝不提前虚亮撤销按钮！
      if (!isUserAction) {
        lastCommittedRef.current = cloneResume(nextData)
        hasPendingUserEditRef.current = false
        updateCanUndoRedo()
        return
      }

      // 用户真实操作：标记待落盘修改，清空重做栈，并即刻点亮撤销按钮
      hasPendingUserEditRef.current = true
      if (futureRef.current.length > 0) {
        futureRef.current = [] // Excel 规则：产生新编辑分支立即清空重做栈
      }
      updateCanUndoRedo()

      // 防抖合并：连续输入期间刷新计时器
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current)
      }

      debounceTimerRef.current = setTimeout(() => {
        debounceTimerRef.current = null
        const currentLive = useResumeV2Store.getState().resumeData
        if (!currentLive || !lastCommittedRef.current) return

        // 若内容产生实质差异，将上一基准压入 past 栈，并推进基准
        if (!isContentEqual(currentLive, lastCommittedRef.current)) {
          pushToPast(lastCommittedRef.current)
          futureRef.current = []
          lastCommittedRef.current = cloneResume(currentLive)
        }

        // 核心修复：无论内容是否变动（包括打字后又删回原样的净零编辑），防抖到期标志本次待落盘编辑结束
        // 若回到原基准且 past 为空，updateCanUndoRedo 会即刻将 canUndo 重新回退置灰！
        hasPendingUserEditRef.current = false
        updateCanUndoRedo()
      }, debounceMs)
    })

    // 3. 全局键盘快捷键监听 (⌘Z / ⌘⇧Z / Ctrl+Y)
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const isInputActive =
        target &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)

      // 若焦点正在文本输入控件内，保留原生单字撤销，不拦截
      if (isInputActive) {
        return
      }

      const hasMetaOrCtrl = e.metaKey || e.ctrlKey
      if (!hasMetaOrCtrl) return

      const isUndo = !e.shiftKey && e.key.toLowerCase() === "z"
      const isRedo =
        (e.shiftKey && e.key.toLowerCase() === "z") || (!e.shiftKey && e.key.toLowerCase() === "y")

      if (isUndo) {
        e.preventDefault()
        undo()
      } else if (isRedo) {
        e.preventDefault()
        redo()
      }
    }

    window.addEventListener("keydown", handleKeyDown)

    // 4. 三位一体卸载清理，杜绝闭包积累与内存泄漏
    return () => {
      unsubscribe()
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current)
        debounceTimerRef.current = null
      }
      window.removeEventListener("keydown", handleKeyDown)
      for (const eventName of GATED_INTERACTION_EVENTS) {
        window.removeEventListener(eventName, markUserInteraction, true)
      }
    }
  }, [debounceMs, mode, pushToPast, undo, redo, updateCanUndoRedo])

  return {
    canUndo,
    canRedo,
    undo,
    redo,
    takeSnapshot,
  }
}
