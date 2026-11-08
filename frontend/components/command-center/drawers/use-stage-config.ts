"use client"

import { useState, useEffect, useCallback } from "react"
import { toast } from "sonner"
import { API_BASE } from "@/lib/api"

/**
 * 阶段配置面板的统一数据骨架：加载态 + GET 读取 + POST/PUT 保存。
 *
 * 各面板此前各写一份 fetch / code 判定 / toast，口径不一
 * （漏判 res.ok、失败静默等历史问题均源于此），收敛到这一处统一维护。
 */

export interface StageConfigState<T> {
  data: T | null
  loading: boolean
  reload: () => Promise<void>
  setData: React.Dispatch<React.SetStateAction<T | null>>
}

export function useStageConfig<T>(
  endpoint: string,
  errorMessage = "读取配置异常"
): StageConfigState<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}${endpoint}`)
      const result = await res.json()
      if (res.ok && result.code === 0 && result.data) {
        setData(result.data)
      } else {
        // 非网络失败（4xx/5xx 带 JSON body、code!=0）此前静默——面板呈现本地默认值，
        // 用户随后点保存会用默认值覆盖线上真实配置（审计 P2-21）。显式报错 + data 保持
        // null（各面板保存入口均有 data 判空守卫，加载失败天然禁保存）
        const detail = typeof result?.detail === "string" ? result.detail : result?.message
        toast.error(`${errorMessage}${detail ? `: ${detail}` : ""}`)
      }
    } catch {
      toast.error(errorMessage)
    } finally {
      setLoading(false)
    }
  }, [endpoint, errorMessage])

  useEffect(() => {
    void reload()
  }, [reload])

  return { data, loading, reload, setData }
}

/** 统一的配置保存：res.ok + code===0 判定、成功/失败 toast，返回是否成功 */
export async function saveStageConfig(
  endpoint: string,
  method: "POST" | "PUT",
  body: unknown,
  successMsg: string
): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
    const result = await res.json()
    if (res.ok && result.code === 0) {
      toast.success(successMsg)
      return true
    }
    toast.error(result.detail || result.msg || "保存失败")
    return false
  } catch {
    toast.error("网络异常，保存失败")
    return false
  }
}
