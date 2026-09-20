/** @type {import('next').NextConfig} */
const nextConfig = {
  typescript: {
    // 类型门禁已开启：全量 tsc 报错清零后于 2026-09-12 关闭豁免，编译期类型错误将直接阻断构建
    ignoreBuildErrors: false,
  },
  images: {
    unoptimized: true,
  },
}

export default nextConfig
