import React from 'react';

export interface BrandConfig {
  name: string;
  keywords: string[];
  logo: React.ComponentType<{ className?: string; size?: number }>;
  theme: string; // 用于 CSS class: band-bytedance, band-feishu, band-loreal, band-ai, etc.
  bgColor?: string;
  borderColor?: string;
  textColor?: string;
}

// ---------------------------------------------------------------------------
// 0. 页眉联系方式微图标 (高保真实心矢量)
// ---------------------------------------------------------------------------

export const PhoneIcon: React.FC<{ className?: string; size?: number }> = ({ className, size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M20.01 15.38c-1.23 0-2.42-.2-3.53-.56a.977.977 0 0 0-1.01.24l-2.2 2.2a15.053 15.053 0 0 1-6.59-6.59l2.2-2.21a.96.96 0 0 0 .25-1.01A11.36 11.36 0 0 1 8.57 3.9c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1 0 9.39 7.61 17 17 17 .55 0 1-.45 1-1v-3.52c0-.55-.45-1-.99-1z" />
  </svg>
);

export const MailIcon: React.FC<{ className?: string; size?: number }> = ({ className, size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z" />
  </svg>
);

export const WeChatIcon: React.FC<{ className?: string; size?: number }> = ({ className, size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M8.5 3C4.36 3 1 5.91 1 9.5c0 2.03 1.05 3.86 2.7 5.06l-.7 2.09 2.45-1.22c.96.36 2 .57 3.05.57.25 0 .5-.01.74-.03-.23-.62-.36-1.28-.36-1.97 0-3.31 3.13-6 7-6 .48 0 .94.04 1.39.12C16.2 5.14 12.65 3 8.5 3zM6 7a1 1 0 1 1 0 2 1 1 0 0 1 0-2zm5 0a1 1 0 1 1 0 2 1 1 0 0 1 0-2zm4.5 4c-3.59 0-6.5 2.46-6.5 5.5 0 1.72.93 3.26 2.37 4.28l-.62 1.87 2.19-1.1c.81.29 1.68.45 2.56.45 3.59 0 6.5-2.46 6.5-5.5s-2.91-5.5-6.5-5.5zm-2 4a.8.8 0 1 1 0-1.6.8.8 0 0 1 0 1.6zm4 0a.8.8 0 1 1 0-1.6.8.8 0 0 1 0 1.6z" />
  </svg>
);

export const UserAvatarIcon: React.FC<{ className?: string; size?: number }> = ({ className, size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
  </svg>
);

// ---------------------------------------------------------------------------
// 1. AI 公司 & 大模型 & AI 编程工具
// ---------------------------------------------------------------------------

export const OpenAILogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1683a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4947zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1683a.0757.0757 0 0 1-.071 0l-4.8303-2.7866A4.504 4.504 0 0 1 2.3408 7.8956zm16.0993 3.8558L12.5973 8.3829l2.02-1.1635a.0804.0804 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.402-.6863zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L8.907 9.2298V6.8974a.0662.0662 0 0 1 .0331-.0615l4.8824-2.8198a4.504 4.504 0 0 1 6.629 4.7064zm-7.9825 4.1444l-2.4346-1.4054 2.4346-1.4054 2.4346 1.4054z" />
  </svg>
);

export const GeminiLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <defs>
      <linearGradient id="gemini-grad" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stopColor="#1ba0e2" />
        <stop offset="50%" stopColor="#9b72cb" />
        <stop offset="100%" stopColor="#d96570" />
      </linearGradient>
    </defs>
    <path
      d="M12 0C12 6.627 6.627 12 0 12C6.627 12 12 17.373 12 24C12 17.373 17.373 12 24 12C17.373 12 12 6.627 12 0Z"
      fill="url(#gemini-grad)"
    />
  </svg>
);

export const ClaudeLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <path
      d="M4.5 10.5L9.5 12L4.5 13.5L3 18.5L7.5 15.5L12 20.5L13.5 15.5L18.5 17L15.5 12.5L20.5 11L15.5 9.5L17 4.5L12.5 7.5L8 2.5L6.5 7.5L1.5 6L4.5 10.5Z"
      fill="#D97757"
    />
    <circle cx="12" cy="12" r="3.5" fill="#C15C3D" />
  </svg>
);

export const KimiLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="5" fill="#18181B" />
    <path d="M7 6V18M7 12L16 6M10 12L17 18" stroke="#38BDF8" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const DeepSeekLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="5" fill="#0D3B66" />
    <path d="M5 14C8 8 16 8 19 14C16 16 8 16 5 14Z" fill="#00A8E8" />
    <circle cx="14" cy="11" r="1.5" fill="#FFFFFF" />
    <path d="M19 14C17.5 12 19 9.5 21 8.5" stroke="#00A8E8" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

export const ZhipuLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="5" fill="#2563EB" />
    <path d="M7 7H17L8 17H17" stroke="#FFFFFF" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    <circle cx="12" cy="12" r="2" fill="#60A5FA" />
  </svg>
);

export const ZCodeLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="5" fill="#4F46E5" />
    <path d="M8 8L5 12L8 16M16 8L19 12L16 16M14 6L10 18" stroke="#FFFFFF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const QoderLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="5" fill="#059669" />
    <circle cx="11" cy="11" r="5" stroke="#FFFFFF" strokeWidth="2" />
    <path d="M15 15L19 19" stroke="#FFFFFF" strokeWidth="2.5" strokeLinecap="round" />
    <path d="M10 9L8 11L10 13M12 9L14 11L12 13" stroke="#A7F3D0" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

// ---------------------------------------------------------------------------
// 2. 飞书 & 字节跳动生态
// ---------------------------------------------------------------------------

export const FeishuLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <path d="M2.5 6.5C8 2 15 2 21.5 6.5L16 13L10.5 10L6.5 15.5L2.5 6.5Z" fill="#3370FF" />
    <path d="M10.5 10L16 13L14 20.5L9 16.5L10.5 10Z" fill="#00D6B9" />
    <path d="M2.5 6.5L6.5 15.5L4 21.5L2.5 6.5Z" fill="#2055CC" />
  </svg>
);

export const ByteDanceLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect x="3" y="3" width="7" height="7" rx="1.5" fill="#325AB4" />
    <rect x="14" y="3" width="7" height="7" rx="1.5" fill="#30C4BB" />
    <rect x="3" y="14" width="7" height="7" rx="1.5" fill="#6B7AFF" />
    <rect x="14" y="14" width="7" height="7" rx="1.5" fill="#325AB4" />
  </svg>
);

export const DouyinLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <circle cx="12" cy="12" r="10" fill="#111827" />
    <path
      d="M15.5 6C15.8 7.5 17 8.8 18.5 9V11.5C17.2 11.5 16 11 15 10.2V14.5C15 17 13 19 10.5 19C8 19 6 17 6 14.5C6 12 8 10 10.5 10C10.9 10 11.2 10.1 11.5 10.2V12.7C11.2 12.6 10.9 12.5 10.5 12.5C9.4 12.5 8.5 13.4 8.5 14.5C8.5 15.6 9.4 16.5 10.5 16.5C11.6 16.5 12.5 15.6 12.5 14.5V6H15.5Z"
      fill="#24F6F0"
    />
    <path
      d="M16 6.5C16.3 8 17.5 9.3 19 9.5V11.8C17.7 11.8 16.5 11.3 15.5 10.5V14.5C15.5 17 13.5 19 11 19C8.5 19 6.5 17 6.5 14.5C6.5 12 8.5 10 11 10C11.4 10 11.7 10.1 12 10.2V12.7C11.7 12.6 11.4 12.5 11 12.5C9.9 12.5 9 13.4 9 14.5C9 15.6 9.9 16.5 11 16.5C12.1 16.5 13 15.6 13 14.5V6.5H16Z"
      fill="#FE2C55"
    />
  </svg>
);

// ---------------------------------------------------------------------------
// 3. 欧莱雅 / 百库 (L'Oréal / Baiku)
// ---------------------------------------------------------------------------

export const LorealLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="4" fill="#1C1917" />
    <circle cx="12" cy="12" r="8.5" stroke="#D4AF37" strokeWidth="1.2" />
    <path d="M8 8V16H12.5" stroke="#FBBF24" strokeWidth="1.8" strokeLinecap="round" />
    <circle cx="15.5" cy="12" r="2.2" stroke="#FBBF24" strokeWidth="1.8" />
  </svg>
);

// ---------------------------------------------------------------------------
// 4. 四大招聘平台 (BOSS直聘 / 智联招聘 / 51job / 猎聘)
// ---------------------------------------------------------------------------

export const BossZhipinLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="4" fill="#00BEBD" />
    <text x="12" y="16" fill="#FFFFFF" fontSize="9" fontWeight="900" textAnchor="middle" fontFamily="sans-serif">
      BOSS
    </text>
  </svg>
);

export const ZhilianLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="4" fill="#198AFA" />
    <circle cx="12" cy="12" r="6" stroke="#FFFFFF" strokeWidth="2" />
    <path d="M9 12H15M12 9V15" stroke="#FFFFFF" strokeWidth="2" strokeLinecap="round" />
  </svg>
);

export const Job51Logo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="4" fill="#FF6000" />
    <text x="12" y="16" fill="#FFFFFF" fontSize="10" fontWeight="900" textAnchor="middle" fontFamily="sans-serif">
      51
    </text>
  </svg>
);

export const LiepinLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="4" fill="#FF7200" />
    <text x="12" y="16.5" fill="#FFFFFF" fontSize="9" fontWeight="900" textAnchor="middle" fontFamily="sans-serif">
      LP
    </text>
  </svg>
);

// ---------------------------------------------------------------------------
// 5. 国内知名互联网科技大厂
// ---------------------------------------------------------------------------

export const AlibabaLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="4" fill="#FF6A00" />
    <path d="M6 16C9 7 15 7 18 16M9 13H15" stroke="#FFFFFF" strokeWidth="2.2" strokeLinecap="round" />
  </svg>
);

export const TencentLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="4" fill="#0052D9" />
    <path d="M6 8H18M12 8V18" stroke="#FFFFFF" strokeWidth="2.5" strokeLinecap="round" />
  </svg>
);

export const MeituanLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="4" fill="#FFD100" />
    <circle cx="12" cy="12" r="5" fill="#1F2937" />
    <circle cx="9" cy="8" r="1.8" fill="#1F2937" />
    <circle cx="15" cy="8" r="1.8" fill="#1F2937" />
  </svg>
);

export const KuaishouLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="4" fill="#FF5000" />
    <rect x="6" y="8" width="12" height="9" rx="2" stroke="#FFFFFF" strokeWidth="2" />
    <circle cx="12" cy="12.5" r="2" fill="#FFFFFF" />
    <circle cx="15" cy="6" r="1.5" fill="#FFFFFF" />
  </svg>
);

export const BaiduLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="4" fill="#2932E1" />
    <circle cx="7" cy="8" r="1.5" fill="#FFFFFF" />
    <circle cx="17" cy="8" r="1.5" fill="#FFFFFF" />
    <circle cx="10" cy="5.5" r="1.5" fill="#FFFFFF" />
    <circle cx="14" cy="5.5" r="1.5" fill="#FFFFFF" />
    <path d="M8 12C8 10 16 10 16 12C16 16 8 16 8 12Z" fill="#E10602" />
  </svg>
);

export const JDLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="4" fill="#E1251B" />
    <text x="12" y="16" fill="#FFFFFF" fontSize="10" fontWeight="900" textAnchor="middle" fontFamily="sans-serif">
      JD
    </text>
  </svg>
);

export const PinduoduoLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="4" fill="#E02E24" />
    <path d="M12 6L15 10L18 8L16 14L12 18L8 14L6 8L9 10L12 6Z" fill="#FFFFFF" />
  </svg>
);

export const XiaohongshuLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="4" fill="#FF2442" />
    <text x="12" y="15.5" fill="#FFFFFF" fontSize="8" fontWeight="bold" textAnchor="middle" fontFamily="sans-serif">
      RED
    </text>
  </svg>
);

export const NetEaseLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="4" fill="#E60012" />
    <text x="12" y="16" fill="#FFFFFF" fontSize="10" fontWeight="bold" textAnchor="middle" fontFamily="sans-serif">
      163
    </text>
  </svg>
);

export const HuaweiLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="4" fill="#CF0A2C" />
    <path d="M12 5C12 8 8 13 8 17M12 5C12 8 16 13 16 17M12 5V18" stroke="#FFFFFF" strokeWidth="2" strokeLinecap="round" />
  </svg>
);

export const XiaomiLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect width="24" height="24" rx="6" fill="#FF6900" />
    <text x="12" y="16" fill="#FFFFFF" fontSize="10" fontWeight="bold" textAnchor="middle" fontFamily="sans-serif">
      MI
    </text>
  </svg>
);

// ---------------------------------------------------------------------------
// 6. 国际顶级科技公司
// ---------------------------------------------------------------------------

export const GoogleLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" fill="#FBBC05" />
    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" fill="#EA4335" />
  </svg>
);

export const MicrosoftLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
    <rect x="2" y="2" width="9" height="9" fill="#F25022" />
    <rect x="13" y="2" width="9" height="9" fill="#7FBA00" />
    <rect x="2" y="13" width="9" height="9" fill="#00A4EF" />
    <rect x="13" y="13" width="9" height="9" fill="#FFB900" />
  </svg>
);

export const AppleLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.81-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M15.97 6.85c.66-.8 1.11-1.92.99-3.04-1 .04-2.16.66-2.84 1.45-.58.68-1.1 1.77-.97 2.87 1.11.08 2.21-.55 2.82-1.28" />
  </svg>
);

export const GitHubBrandLogo: React.FC<{ className?: string; size?: number }> = ({ className, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path
      fillRule="evenodd"
      clipRule="evenodd"
      d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
    />
  </svg>
);

// ---------------------------------------------------------------------------
// 智能品牌规则库 (按优先级排序)
// ---------------------------------------------------------------------------

export const BRAND_REGISTRY: BrandConfig[] = [
  // 1. AI 公司 & 大模型
  { name: 'OpenAI', keywords: ['openai', 'chatgpt', 'gpt-4', 'gpt-3', 'gpt-5'], logo: OpenAILogo, theme: 'openai', bgColor: '#F4F4F5', borderColor: '#E4E4E7' },
  { name: 'Gemini', keywords: ['gemini', 'deepmind', 'google gemini'], logo: GeminiLogo, theme: 'gemini', bgColor: '#EEF2FF', borderColor: '#C7D2FE' },
  { name: 'Claude', keywords: ['claude', 'anthropic'], logo: ClaudeLogo, theme: 'claude', bgColor: '#FEF3C7', borderColor: '#FDE68A' },
  { name: 'Kimi', keywords: ['kimi', 'moonshot', '月之暗面'], logo: KimiLogo, theme: 'kimi', bgColor: '#F4F4F5', borderColor: '#E4E4E7' },
  { name: 'DeepSeek', keywords: ['deepseek', '深度求索'], logo: DeepSeekLogo, theme: 'deepseek', bgColor: '#E0F2FE', borderColor: '#BAE6FD' },
  { name: '智谱AI', keywords: ['智谱', 'zhipu', 'chatglm', 'glm-4', 'glm-5'], logo: ZhipuLogo, theme: 'zhipu', bgColor: '#EFF6FF', borderColor: '#BFDBFE' },
  { name: 'ZCode', keywords: ['zcode', 'z-code'], logo: ZCodeLogo, theme: 'zcode', bgColor: '#EEF2FF', borderColor: '#C7D2FE' },
  { name: 'Qoder', keywords: ['qoder', 'q-code'], logo: QoderLogo, theme: 'qoder', bgColor: '#ECFDF5', borderColor: '#A7F3D0' },

  // 2. 飞书 & 字节跳动生态
  { name: '飞书', keywords: ['飞书', 'feishu', 'lark'], logo: FeishuLogo, theme: 'feishu', bgColor: '#EFF6FF', borderColor: '#BFDBFE' },
  { name: '抖音', keywords: ['抖音', 'douyin', 'tiktok', '剪映', '懂车帝'], logo: DouyinLogo, theme: 'douyin', bgColor: '#F8FAFC', borderColor: '#E2E8F0' },
  { name: '字节跳动', keywords: ['字节跳动', 'bytedance', '字节'], logo: ByteDanceLogo, theme: 'bytedance', bgColor: '#EFF6FF', borderColor: '#DBEAFE' },

  // 3. 欧莱雅 / 百库
  { name: '欧莱雅百库', keywords: ['欧莱雅', '百库', 'loreal', 'l\'oreal', 'baiku'], logo: LorealLogo, theme: 'loreal', bgColor: '#FAFAF9', borderColor: '#E7E5E4' },

  // 4. 求职招聘平台 (可直接用于公司或项目)
  { name: 'BOSS直聘', keywords: ['boss直聘', 'boss', 'zhipin'], logo: BossZhipinLogo, theme: 'boss', bgColor: '#F0FDFA', borderColor: '#99F6E4' },
  { name: '智联招聘', keywords: ['智联招聘', '智联', 'zhaopin'], logo: ZhilianLogo, theme: 'zhilian', bgColor: '#EFF6FF', borderColor: '#BFDBFE' },
  { name: '前程无忧', keywords: ['前程无忧', '51job', '无忧'], logo: Job51Logo, theme: 'job51', bgColor: '#FFF7ED', borderColor: '#FED7AA' },
  { name: '猎聘', keywords: ['猎聘', 'liepin'], logo: LiepinLogo, theme: 'liepin', bgColor: '#FFF7ED', borderColor: '#FED7AA' },

  // 5. 国内大厂
  { name: '阿里巴巴', keywords: ['阿里', 'alibaba', '淘宝', 'taobao', '天猫', 'tmall', '阿里云', '蚂蚁', '支付宝', '钉钉'], logo: AlibabaLogo, theme: 'alibaba', bgColor: '#FFF7ED', borderColor: '#FFEDD5' },
  { name: '腾讯', keywords: ['腾讯', 'tencent', '微信', 'wechat', 'qq', '腾讯云'], logo: TencentLogo, theme: 'tencent', bgColor: '#EFF6FF', borderColor: '#DBEAFE' },
  { name: '美团', keywords: ['美团', 'meituan', '大众点评'], logo: MeituanLogo, theme: 'meituan', bgColor: '#FEFCE8', borderColor: '#FEF08A' },
  { name: '快手', keywords: ['快手', 'kuaishou'], logo: KuaishouLogo, theme: 'kuaishou', bgColor: '#FFF1F2', borderColor: '#FFE4E6' },
  { name: '百度', keywords: ['百度', 'baidu', '文心一言'], logo: BaiduLogo, theme: 'baidu', bgColor: '#EEF2FF', borderColor: '#E0E7FF' },
  { name: '京东', keywords: ['京东', 'jd', 'jd.com', '京东物流'], logo: JDLogo, theme: 'jd', bgColor: '#FEF2F2', borderColor: '#FEE2E2' },
  { name: '拼多多', keywords: ['拼多多', 'pinduoduo', 'pdd', 'temu'], logo: PinduoduoLogo, theme: 'pdd', bgColor: '#FEF2F2', borderColor: '#FEE2E2' },
  { name: '小红书', keywords: ['小红书', 'xiaohongshu', 'redbook'], logo: XiaohongshuLogo, theme: 'xiaohongshu', bgColor: '#FFF1F2', borderColor: '#FFE4E6' },
  { name: '网易', keywords: ['网易', 'netease', '163'], logo: NetEaseLogo, theme: 'netease', bgColor: '#FEF2F2', borderColor: '#FEE2E2' },
  { name: '华为', keywords: ['华为', 'huawei', '荣耀', 'honor', '鸿蒙'], logo: HuaweiLogo, theme: 'huawei', bgColor: '#FEF2F2', borderColor: '#FEE2E2' },
  { name: '小米', keywords: ['小米', 'xiaomi', 'redmi'], logo: XiaomiLogo, theme: 'xiaomi', bgColor: '#FFF7ED', borderColor: '#FFEDD5' },

  // 6. 国际顶级科技公司
  { name: 'Google', keywords: ['google', '谷歌', 'alphabet'], logo: GoogleLogo, theme: 'google', bgColor: '#F8FAFC', borderColor: '#E2E8F0' },
  { name: 'Microsoft', keywords: ['microsoft', '微软', 'azure'], logo: MicrosoftLogo, theme: 'microsoft', bgColor: '#F8FAFC', borderColor: '#E2E8F0' },
  { name: 'Apple', keywords: ['apple', '苹果', 'ios', 'macos'], logo: AppleLogo, theme: 'apple', bgColor: '#F8FAFC', borderColor: '#E2E8F0' },
  { name: 'GitHub', keywords: ['github', 'git'], logo: GitHubBrandLogo, theme: 'github', bgColor: '#F4F4F5', borderColor: '#E4E4E7' },
];

/**
 * 智能解析公司/平台品牌
 * @param companyName 公司名称字符串
 * @returns 命中的 BrandConfig，若未匹配则返回 null（小公司不显示 logo）
 */
export function resolveCompanyBrand(companyName?: string | null): BrandConfig | null {
  if (!companyName) return null;
  const lower = companyName.toLowerCase().replace(/\s+/g, '');
  for (const brand of BRAND_REGISTRY) {
    if (brand.keywords.some(kw => lower.includes(kw.toLowerCase()))) {
      return brand;
    }
  }
  return null;
}

/**
 * 根据平台 key 解析求职平台徽章
 */
export function resolvePlatformLogo(platformKey: string): React.ComponentType<{ className?: string; size?: number }> | null {
  const k = platformKey.toLowerCase();
  if (k.includes('boss')) return BossZhipinLogo;
  if (k.includes('zhilian') || k.includes('智联')) return ZhilianLogo;
  if (k.includes('51job') || k.includes('前程无忧') || k.includes('job51')) return Job51Logo;
  if (k.includes('liepin') || k.includes('猎聘')) return LiepinLogo;
  if (k.includes('feishu') || k.includes('飞书')) return FeishuLogo;
  if (k.includes('github')) return GitHubBrandLogo;
  if (k.includes('openai')) return OpenAILogo;
  if (k.includes('gemini')) return GeminiLogo;
  if (k.includes('claude')) return ClaudeLogo;
  if (k.includes('kimi')) return KimiLogo;
  if (k.includes('deepseek')) return DeepSeekLogo;
  return null;
}
