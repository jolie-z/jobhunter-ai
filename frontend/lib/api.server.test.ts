// @vitest-environment node
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { getApiBase } from './api'

// 服务端（无 window）分支：/print/* 打印页 Server Component 的 SSR fetch 后端地址解析。
// 0.3.8 回归：壳把后端首选端口 8000→8978 后，服务端回落写死的 8000 → ECONNREFUSED →
// 投递附件 PDF 渲染成「Failed to load resume data / fetch failed」（Win 沙盒实测）。
// 修复：优先读壳注入前端进程的 BACKEND_BASE_URL（非 NEXT_PUBLIC_ 前缀，运行时读取不被内联）。

const saved = {
  backend: process.env.BACKEND_BASE_URL,
  pub: process.env.NEXT_PUBLIC_API_URL,
}

beforeEach(() => {
  delete process.env.BACKEND_BASE_URL
  delete process.env.NEXT_PUBLIC_API_URL
})

afterEach(() => {
  if (saved.backend === undefined) delete process.env.BACKEND_BASE_URL
  else process.env.BACKEND_BASE_URL = saved.backend
  if (saved.pub === undefined) delete process.env.NEXT_PUBLIC_API_URL
  else process.env.NEXT_PUBLIC_API_URL = saved.pub
})

describe('getApiBase 服务端分支（Server Component / SSR）', () => {
  it('本测试运行在 node 环境：无 window', () => {
    expect(typeof window).toBe('undefined')
  })

  it('读壳注入的 BACKEND_BASE_URL（后端动态端口）', () => {
    process.env.BACKEND_BASE_URL = 'http://127.0.0.1:8978'
    expect(getApiBase()).toBe('http://127.0.0.1:8978')
  })

  it('尾部 / 与 /api 段被剥掉，与浏览器分支同口径', () => {
    process.env.BACKEND_BASE_URL = 'http://127.0.0.1:8978/api/'
    expect(getApiBase()).toBe('http://127.0.0.1:8978')
  })

  it('BACKEND_BASE_URL 优先于构建期 NEXT_PUBLIC_API_URL', () => {
    process.env.BACKEND_BASE_URL = 'http://127.0.0.1:8978'
    process.env.NEXT_PUBLIC_API_URL = 'http://build-time-host:8000'
    expect(getApiBase()).toBe('http://127.0.0.1:8978')
  })

  it('未注入时回落 127.0.0.1:8000（浏览器直开 dev 的历史约定不变）', () => {
    expect(getApiBase()).toBe('http://127.0.0.1:8000')
  })
})
