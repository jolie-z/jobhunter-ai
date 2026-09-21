"use client"

// 功能就绪度预检共享工具（readiness 端点的三处消费点单点复用，防逻辑漂移）
// 返回值语义：null = 后端不可达/无法判断（调用方不拦截，由后端 400 兜底）；
//            [] = 该通道已就绪；非空 = 缺失字段 key 列表（调用方弹配置引导）

import { apiFetch } from "@/lib/api"

export type ReadinessChannel = "vision" | "llm"

const DEFAULT_MISSING: Record<ReadinessChannel, string> = {
    vision: "VISION_MODEL",
    llm: "OPENAI_API_KEY",
}

export async function fetchMissingKeys(channel: ReadinessChannel): Promise<string[] | null> {
    try {
        const res = await apiFetch(`/api/settings/readiness`)
        if (!res.ok) return null
        const data = await res.json()
        if (data?.code !== 0) return null
        const readyKey = channel === "vision" ? "vision_ready" : "main_llm_ready"
        if (data.data?.[readyKey]) return []
        return data.data?.missing?.[channel] || [DEFAULT_MISSING[channel]]
    } catch {
        return null
    }
}
