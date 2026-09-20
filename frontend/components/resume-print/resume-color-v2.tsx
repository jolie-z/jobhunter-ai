import React from 'react';
import ReactMarkdown from 'react-markdown';
import { Phone, Mail, MapPin, Globe, Github, Linkedin, ExternalLink } from 'lucide-react';
import { ResumeDataV2 } from '@/types/resume';
import { stripConfidenceTags } from '@/lib/utils/text-formatters';
import { PhoneIcon, MailIcon, WeChatIcon, UserAvatarIcon, GitHubBrandLogo, resolveCompanyBrand, resolvePlatformLogo, BossZhipinLogo, ZhilianLogo, Job51Logo, LiepinLogo } from './brand-logos';
import baseStyles from './styles/_base.module.css';
import styles from './styles/color-v2.module.css';

interface ResumeColorV2Props {
  data: ResumeDataV2 & { avatar_url?: string | null };
}

/** 联系方式 key → 图标与链接前缀 */
function resolveMetaIcon(key: string): React.ComponentType<{ className?: string }> | null {
  const k = key.toLowerCase();
  if (k.includes('phone') || k === '电话') return Phone;
  if (k.includes('email') || k === '邮箱') return Mail;
  if (k.includes('github')) return Github;
  if (k.includes('linkedin')) return Linkedin;
  if (k.includes('location') || k.includes('城市') || k.includes('city')) return MapPin;
  if (k.includes('website') || k.includes('主页') || k.includes('blog')) return Globe;
  return null;
}

function resolveMetaHref(key: string, value: string): string | null {
  const k = key.toLowerCase();
  if (k.includes('phone') || k === '电话') return `tel:${value}`;
  if (k.includes('email') || k === '邮箱') return `mailto:${value}`;
  if (/^https?:\/\//.test(value)) return value;
  if (k.includes('github') || k.includes('website') || k.includes('主页') || k.includes('linkedin') || k.includes('blog') || value.includes('github') || value.startsWith('www.')) {
    return `https://${value}`;
  }
  return null;
}

function toDescString(desc: unknown): string {
  if (Array.isArray(desc)) return desc.map(String).join('\n');
  if (typeof desc === 'string' || typeof desc === 'number') return String(desc);
  return '';
}

/** 智能检测文本中是否提及 4 大求职平台，生成微胶囊徽章组 */
function detectPlatformPills(text: string): React.ReactNode | null {
  if (!text) return null;
  const lower = text.toLowerCase();
  const pills: Array<{ name: string; Logo: React.ComponentType<{ size?: number }> }> = [];

  if (lower.includes('boss') || lower.includes('直聘')) {
    pills.push({ name: 'BOSS直聘', Logo: BossZhipinLogo });
  }
  if (lower.includes('zhilian') || lower.includes('智联')) {
    pills.push({ name: '智联招聘', Logo: ZhilianLogo });
  }
  if (lower.includes('51job') || lower.includes('前程无忧') || lower.includes('job51')) {
    pills.push({ name: '前程无忧', Logo: Job51Logo });
  }
  if (lower.includes('liepin') || lower.includes('猎聘')) {
    pills.push({ name: '猎聘', Logo: LiepinLogo });
  }

  if (pills.length === 0) return null;

  return (
    <span className={styles.platformBadgeGroup}>
      {pills.map((p, i) => (
        <span key={i} className={styles.platformPill}>
          <p.Logo size={12} />
          <span>{p.name}</span>
        </span>
      ))}
    </span>
  );
}

/** 经历主条带：全宽圆角底带 + 官方品牌 Logo / 平台徽章组 */
const EntryBand: React.FC<{
  companyName: string;
  role?: string;
  years?: string;
  location?: string;
  link?: string;
  extraPills?: React.ReactNode;
}> = ({ companyName, role, years, location, link, extraPills }) => {
  const brand = resolveCompanyBrand(companyName);
  const bandThemeClass = brand ? (styles[`band-${brand.theme}`] || styles['band-default']) : styles['band-default'];
  const BrandLogo = brand?.logo;

  return (
    <div className={`${styles.entryBand} ${bandThemeClass}`}>
      {BrandLogo && (
        <span className={styles.brandIcon}>
          <BrandLogo size={17} />
        </span>
      )}
      <span className={styles.entryCompany}>{companyName}</span>
      {years && <span className={styles.entryYears}>--- {years}</span>}
      {role && (
        <>
          <span className={styles.entryDivider}>|</span>
          <span className={styles.entryRole}>{role}</span>
        </>
      )}
      {location && (
        <>
          <span className={styles.entryDivider}>|</span>
          <span className={styles.entryRole}>{location}</span>
        </>
      )}
      {extraPills}
      {link && (
        <a href={link} target="_blank" rel="noopener noreferrer" className={styles.entryLink}>
          业务详情 →
        </a>
      )}
    </div>
  );
};

const MarkdownBlock: React.FC<{ children: string; className?: string }> = ({ children, className }) => (
  <div className={`${styles.markdown} ${baseStyles['resume-text-sm']} ${className || ''}`}>
    <ReactMarkdown
      components={{
        p: ({ node, ...props }) => <span className="block" {...props} />,
        // 自动将流程箭头 → 赋予轻度高亮
        strong: ({ node, children, ...props }) => {
          return <strong {...props}>{children}</strong>;
        }
      }}
    >
      {stripConfidenceTags(children)}
    </ReactMarkdown>
  </div>
);

export const ResumeColorV2: React.FC<ResumeColorV2Props> = ({ data }) => {
  const {
    personalInfo,
    summary,
    workExperience = [],
    education = [],
    personalProjects = [],
    additional,
    moduleOrder = ["summary", "workExperience", "personalProjects", "education", "additional"],
    moduleTitles = {},
    customModules = {}
  } = data || {};

  const avatarUrl = data.personalInfo?.avatar_url || data.avatar_url;

  const renderSection = (modKey: string) => {
    const title = moduleTitles[modKey] || {
      summary: '个人总结',
      workExperience: '实习与工作经历',
      personalProjects: '核心项目经历',
      education: '教育背景',
      additional: '专业技能与其他'
    }[modKey] || modKey;

    switch (modKey) {
      case 'summary':
        if (!summary) return null;
        return (
          <div key={modKey} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitle}>{title}</h3>
            {/* 章节高亮 Callout 框 */}
            <div className={styles.sectionCallout}>
              <MarkdownBlock>{summary}</MarkdownBlock>
            </div>
          </div>
        );

      case 'workExperience':
        if (!workExperience || workExperience.length === 0) return null;
        return (
          <div key={modKey} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitle}>{title}</h3>
            <div className={baseStyles['resume-items']}>
              {workExperience.map((exp, idx) => {
                // 检测经历中是否涉及多平台
                const descStr = toDescString(exp.description);
                const platformPills = detectPlatformPills(exp.company + ' ' + (exp.title || '') + ' ' + descStr);

                return (
                  <div key={idx} className={baseStyles['resume-item']}>
                    <EntryBand
                      companyName={exp.company}
                      role={exp.title}
                      years={exp.years}
                      location={exp.location || undefined}
                      extraPills={platformPills}
                    />
                    {descStr && (
                      <MarkdownBlock>{descStr}</MarkdownBlock>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );

      case 'personalProjects':
        if (!personalProjects || personalProjects.length === 0) return null;
        return (
          <div key={modKey} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitle}>{title}</h3>
            <div className={baseStyles['resume-items']}>
              {personalProjects.map((project, idx) => {
                const descStr = toDescString(project.description);
                const platformPills = detectPlatformPills(project.name + ' ' + (project.role || '') + ' ' + descStr);

                return (
                  <div key={idx} className={baseStyles['resume-item']}>
                    <EntryBand
                      companyName={project.name}
                      role={project.role}
                      years={project.years}
                      extraPills={platformPills}
                    />
                    {descStr && (
                      <MarkdownBlock>{descStr}</MarkdownBlock>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );

      case 'education':
        if (!education || education.length === 0) return null;
        return (
          <div key={modKey} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitle}>{title}</h3>
            <div className={baseStyles['resume-items']}>
              {education.map((edu, idx) => (
                <div key={idx} className={baseStyles['resume-item']}>
                  <EntryBand
                    companyName={edu.institution}
                    role={edu.major ? `${edu.major} · ${edu.degree}` : edu.degree}
                    years={edu.years}
                  />
                  {edu.description && (
                    <MarkdownBlock>{edu.description}</MarkdownBlock>
                  )}
                </div>
              ))}
            </div>
          </div>
        );

      case 'additional':
        if (!additional) return null;
        const { technicalSkills = [], languages = [], certificationsTraining = [] } = additional;
        const hasContent = technicalSkills.length > 0 || languages.length > 0 || certificationsTraining.length > 0;
        if (!hasContent) return null;
        return (
          <div key={modKey} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitle}>{title}</h3>
            <div className={`text-justify ${styles.markdown} ${baseStyles['resume-text-sm']}`}>
              {technicalSkills.length > 0 && (
                <ReactMarkdown components={{ p: ({ node, ...props }) => <span className="block" {...props} /> }}>
                  {stripConfidenceTags(technicalSkills.join('\n'))}
                </ReactMarkdown>
              )}
              {languages.length > 0 && (
                <div className="mt-1"><strong>语言能力：</strong>{languages.join(' / ')}</div>
              )}
              {certificationsTraining.length > 0 && (
                <div className="mt-1"><strong>证书与培训：</strong>{certificationsTraining.join(' / ')}</div>
              )}
            </div>
          </div>
        );

      default: {
        const customItems = customModules?.[modKey];
        if (!customItems || customItems.length === 0) return null;
        return (
          <div key={modKey} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitle}>{title}</h3>
            <div className={baseStyles['resume-items']}>
              {customItems.map((item, idx) => {
                const descStr = toDescString(item.description);
                return (
                  <div key={idx} className={baseStyles['resume-item']}>
                    <EntryBand
                      companyName={item.company || ''}
                      role={item.title || ''}
                      years={item.years}
                      location={item.location || undefined}
                    />
                    {descStr && (
                      <MarkdownBlock>{descStr}</MarkdownBlock>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      }
    }
  };

  return (
    <div className={`${styles.container} ${baseStyles['resume-body']} bg-white text-black`}>
      {/* 1. 个人信息部分 (左上角大字姓名 + 电话/邮箱/微信 + Title + GitHub + 右侧照片) */}
      {personalInfo && (
        <header className={styles.headerContainer}>
          {/* 1.5 照片放在个人信息的右侧 */}
          {avatarUrl && (
            <div className="absolute right-0 top-0 w-[74px] h-[98px] overflow-hidden bg-gray-100 rounded border border-gray-200 shadow-xs">
              <img src={avatarUrl} alt="Avatar" className="w-full h-full object-cover" />
            </div>
          )}

          <div style={avatarUrl ? { paddingRight: '90px' } : undefined}>
            {/* 1.1 左上角是名字 (比其余字体大，中文汉字间留出一个空格) */}
            {personalInfo.name && (
              <h1 className={styles.headerName}>
                {/^[\u4e00-\u9fa5]{2,4}$/.test(personalInfo.name.replace(/\s+/g, ''))
                  ? personalInfo.name.replace(/\s+/g, '').split('').join(' ')
                  : personalInfo.name}
              </h1>
            )}

            {/* 1.2 名字下方是 电话，邮箱，微信，用 丨 字符隔开 */}
            <div className={styles.headerContactRow}>
              {personalInfo.phone && (
                <span className={styles.headerItem}>
                  <span className={styles.headerIcon}><PhoneIcon size={12} /></span>
                  <span>{personalInfo.phone}</span>
                </span>
              )}

              {personalInfo.phone && personalInfo.email && (
                <span className={styles.headerDivider}>丨</span>
              )}

              {personalInfo.email && (
                <span className={styles.headerItem}>
                  <span className={styles.headerIcon}><MailIcon size={12} /></span>
                  <a href={`mailto:${personalInfo.email}`} className={styles.link}>{personalInfo.email}</a>
                </span>
              )}

              {((personalInfo as any).wechat || (personalInfo as any).wx || personalInfo.phone) && (
                <>
                  <span className={styles.headerDivider}>丨</span>
                  <span className={styles.headerItem}>
                    <span className={styles.headerIcon}><WeChatIcon size={13} /></span>
                    <span>{(personalInfo as any).wechat || (personalInfo as any).wx || personalInfo.phone}</span>
                  </span>
                </>
              )}

              {personalInfo.location && (
                <>
                  <span className={styles.headerDivider}>丨</span>
                  <span className={styles.headerItem}>
                    <span className={styles.headerIcon}><MapPin className="size-3" /></span>
                    <span>{personalInfo.location}</span>
                  </span>
                </>
              )}
            </div>

            {/* 1.3 再下方是 Full-Stack AI Agent Developer */}
            <div className={styles.headerTitleRow}>
              <span className={styles.headerIcon}><UserAvatarIcon size={12} /></span>
              <span>{personalInfo.title || "Full-Stack AI Agent Developer"}</span>
            </div>

            {/* 1.4 再下方是 GitHub (Creator & Owner) */}
            <div className={styles.headerGithubRow}>
              <span className={styles.headerItem}>
                <span className={styles.headerIcon}><GitHubBrandLogo size={13} /></span>
                <a
                  href={(() => {
                    const raw = personalInfo.website || "github.com/your-username";
                    return raw.startsWith("http") ? raw : `https://${raw.replace(/^\/+/, "")}`;
                  })()}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.link}
                >
                  {(() => {
                    const raw = personalInfo.website || "github.com/your-username";
                    return raw.replace(/^https?:\/\//, "").replace(/\/$/, "");
                  })()}
                </a>
              </span>
              <span className={styles.headerRepoTag}>
                （Creator & Owner of Auto-JobHunter 全链路自动求职中台）
              </span>
            </div>
          </div>
        </header>
      )}

      {/* 模块根据 moduleOrder 渲染 */}
      {[...new Set(moduleOrder)].map(modKey => renderSection(modKey))}
    </div>
  );
};

export default ResumeColorV2;
