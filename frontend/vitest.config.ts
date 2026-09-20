import { defineConfig } from 'vitest/config'
import path from 'path'

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    // 历史账（2026-09-19/20 两专项核实）：曾有的全量"随机"失败=负载敏感超时竞态，
    // 根源是 tab 系组件测试未包 act 的异步更新拖慢时序击穿默认 5s。act 警告已根治
    // （2026-09-20 专项：7 文件 renderAsync/act 冲刷，0 警告 4 轮全量含 shuffle），
    // 随后默认 5s 下普通+CPU 满载双轮 194/194 全绿，testTimeout 覆盖已移除。
    // 另：pool:'forks' 实测亦全绿但全量耗时 13s→58s（4 倍），无必要不采用。
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './')
    }
  }
})
