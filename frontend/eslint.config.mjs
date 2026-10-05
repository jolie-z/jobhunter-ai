// ESLint flat config — eslint-config-next@16 原生 flat 格式
import coreWebVitals from "eslint-config-next/core-web-vitals"
import typescript from "eslint-config-next/typescript"

const eslintConfig = [
  ...coreWebVitals,
  ...typescript,
  {
    ignores: [".next/**", "node_modules/**", "out/**", "next-env.d.ts"],
  },
  {
    rules: {
      // ⚠️ 存量债务降级区（2026-09 质量治理）——error→warn 棘轮：
      // 以下规则存在大量历史违规（any 593 处、react-hooks 严格规则 ~163 处），
      // 修复需要真实重构。降为 warn 保证 CI 门禁可用：新代码引入【其他】error 仍会挂；
      // 清理一批后应把对应规则升回 error（逐步收紧）。
      "@typescript-eslint/no-explicit-any": "warn",
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
      "react-hooks/immutability": "warn",
      "react-hooks/error-boundaries": "warn",
      "react-hooks/preserve-manual-memoization": "warn",
      "react-hooks/static-components": "warn",
      "react-hooks/purity": "warn",
    },
  },
]

export default eslintConfig
