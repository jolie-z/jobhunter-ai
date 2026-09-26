import type { Metadata } from 'next'
import { Analytics } from '@vercel/analytics/next'
import { Toaster } from '@/components/ui/toaster'
import { Toaster as SonnerToaster } from '@/components/ui/sonner'
import { GlobalTerminalDrawer } from '@/components/global/global-terminal-drawer'
import { SetupGuideProvider } from '@/components/dashboard/setup-guide/setup-guide-provider'
import './globals.css'

export const metadata: Metadata = {
  title: 'JobHunter AI - 智能求职助手',
  description: 'AI驱动的求职优化平台，智能简历定制与岗位匹配',
  generator: 'v0.app',
  icons: {
    icon: [
      {
        url: '/icon-light-32x32.png',
        media: '(prefers-color-scheme: light)',
      },
      {
        url: '/icon-dark-32x32.png',
        media: '(prefers-color-scheme: dark)',
      },
      {
        url: '/icon.svg',
        type: 'image/svg+xml',
      },
    ],
    apple: '/apple-icon.png',
  },
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="font-sans antialiased">
        <SetupGuideProvider>
          {children}
          <GlobalTerminalDrawer />
          <Toaster />
          {/* 指挥中心全族用 sonner toast（此前容器从未挂载，其 toast 全部静默丢失——
              门禁拦截/启动失败等反馈用户从未见过，2026-09-26 真机验证发现），两套容器并存各管各系 */}
          <SonnerToaster position="bottom-right" />
        </SetupGuideProvider>
        <Analytics />
      </body>
    </html>
  )
}
