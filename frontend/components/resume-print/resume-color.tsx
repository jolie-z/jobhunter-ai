import React from 'react';
import ReactMarkdown from 'react-markdown';
import { Phone, Mail, MapPin, Globe, Github, Linkedin } from 'lucide-react';
import { ResumeDataV2 } from '@/types/resume';
import { stripConfidenceTags } from '@/lib/utils/text-formatters';
import baseStyles from './styles/_base.module.css';
import styles from './styles/color.module.css';

interface ResumeColorProps {
  data: ResumeDataV2 & { avatar_url?: string | null };
}

/** 联系方式 key → 图标与链接前缀（普通文本字段返回 null 图标） */
function resolveMetaIcon(key: string): React.ComponentType<{ className?: string }> | null {
  const k = key.toLowerCase();
  if (k.includes('phone') || k === '电话') return Phone;
  if (k.includes('email') || k === '邮箱') return Mail;
  if (k.includes('github')) return Github;
  if (k.includes('linkedin')) return Linkedin;
  if (k.includes('location') || k.includes('城市') || k === 'location') return MapPin;
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

/** 条目头：浅色底带横条（借鉴参考模版的公司条） */
const EntryBand: React.FC<{
  primary: string;
  secondary?: string;
  meta?: string;
}> = ({ primary, secondary, meta }) => (
  <div className={styles.entryBand}>
    <span className={styles.entryCompany}>{primary}</span>
    {secondary && (
      <>
        <span className={styles.entryDivider}>|</span>
        <span className={styles.entryRole}>{secondary}</span>
      </>
    )}
    {meta && <span className={styles.entryMeta}>{meta}</span>}
  </div>
);

const MarkdownBlock: React.FC<{ children: string; className?: string }> = ({ children, className }) => (
  <div className={`${styles.markdown} ${baseStyles['resume-text-sm']} ${className || ''}`}>
    <ReactMarkdown components={{ p: ({ node, ...props }) => <span className="block" {...props} /> }}>
      {stripConfidenceTags(children)}
    </ReactMarkdown>
  </div>
);

export const ResumeColor: React.FC<ResumeColorProps> = ({ data }) => {
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

  const renderSection = (modKey: string) => {
    const title = moduleTitles[modKey] || modKey;

    switch (modKey) {
      case 'summary':
        if (!summary) return null;
        return (
          <div key={modKey} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitle}>{title}</h3>
            <MarkdownBlock className="text-justify">{summary}</MarkdownBlock>
          </div>
        );

      case 'workExperience':
        if (!workExperience || workExperience.length === 0) return null;
        return (
          <div key={modKey} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitle}>{title}</h3>
            <div className={baseStyles['resume-items']}>
              {workExperience.map((exp, idx) => (
                <div key={idx} className={baseStyles['resume-item']}>
                  <EntryBand
                    primary={exp.company}
                    secondary={exp.title}
                    meta={exp.years}
                  />
                  {exp.location && (
                    <div className={`${baseStyles['resume-text-sm']} mb-1 text-right`}>{exp.location}</div>
                  )}
                  {exp.description && exp.description.length > 0 && (
                    <MarkdownBlock>{exp.description.join('\n')}</MarkdownBlock>
                  )}
                </div>
              ))}
            </div>
          </div>
        );

      case 'personalProjects':
        if (!personalProjects || personalProjects.length === 0) return null;
        return (
          <div key={modKey} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitle}>{title}</h3>
            <div className={baseStyles['resume-items']}>
              {personalProjects.map((project, idx) => (
                <div key={idx} className={baseStyles['resume-item']}>
                  <EntryBand
                    primary={project.name}
                    secondary={project.role}
                    meta={project.years}
                  />
                  {project.description && project.description.length > 0 && (
                    <MarkdownBlock>{project.description.join('\n')}</MarkdownBlock>
                  )}
                </div>
              ))}
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
                  <div className={styles.educationBand}>
                    <span className={styles.educationSchool}>{edu.institution}</span>
                    <span className={styles.educationMajor}>
                      {edu.major ? `${edu.major} · ${edu.degree}` : edu.degree}
                    </span>
                    <span className={styles.educationYears}>{edu.years}</span>
                  </div>
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
                <div className="mt-1"><strong>语言：</strong>{languages.join(' / ')}</div>
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
              {customItems.map((item, idx) => (
                <div key={idx} className={baseStyles['resume-item']}>
                  <EntryBand
                    primary={item.company || ''}
                    secondary={item.title || ''}
                    meta={item.years}
                  />
                  {item.description && item.description.length > 0 && (
                    <MarkdownBlock>{item.description.join('\n')}</MarkdownBlock>
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      }
    }
  };

  return (
    <div className={`${styles.container} ${baseStyles['resume-body']} bg-white text-black`}>
      {/* 页眉：姓名（主色）+ 图标联系行 + 求职意向 */}
      {personalInfo && (
        <header className={baseStyles['resume-header']}>
          {(data.personalInfo?.avatar_url || data.avatar_url) && (
            <div className="absolute right-0 top-0 w-[75px] h-[100px] overflow-hidden bg-gray-100 rounded border border-gray-200 shadow-sm">
              <img src={(data.personalInfo?.avatar_url || data.avatar_url) as string} alt="Avatar" className="w-full h-full object-cover" />
            </div>
          )}

          <div style={(data.personalInfo?.avatar_url || data.avatar_url) ? { padding: '0 90px' } : undefined}>
            {personalInfo.name && (
              <h1 className={`${styles.headerName} mb-2`}>
                {/^[\u4e00-\u9fa5]{2,4}$/.test(personalInfo.name.replace(/\s+/g, ''))
                  ? personalInfo.name.replace(/\s+/g, '').split('').join(' ')
                  : personalInfo.name}
              </h1>
            )}

            <div className={`${styles.metaRow} mb-1`}>
              {(() => {
                const items: React.ReactNode[] = [];
                const { name: _name, title: _title, avatar_url: _avatar, ...rest } = personalInfo;

                Object.entries(rest).forEach(([key, value]) => {
                  if (!value) return;
                  const Icon = resolveMetaIcon(key);
                  const href = resolveMetaHref(key, String(value));
                  let displayText = String(value);
                  if (href && href.startsWith('https://')) {
                    displayText = displayText.replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/$/, '');
                  }

                  items.push(
                    <span key={key} className={styles.metaItem}>
                      {Icon && <Icon className={styles.metaIcon} />}
                      {href ? (
                        <a href={href} target="_blank" rel="noopener noreferrer" className={styles.link}>{displayText}</a>
                      ) : (
                        <span>{displayText}</span>
                      )}
                    </span>
                  );
                });

                return items.map((item, idx) => (
                  <React.Fragment key={idx}>
                    {idx > 0 && <span style={{ color: 'var(--color-accent-soft)', opacity: 0.5 }}>丨</span>}
                    {item}
                  </React.Fragment>
                ));
              })()}
            </div>

            {personalInfo.title && (
              <div className={styles.intentRow}>
                <span className={styles.intentLabel}>求职意向:</span>
                <span>{personalInfo.title}</span>
              </div>
            )}
          </div>
        </header>
      )}

      {[...new Set(moduleOrder)].map(modKey => renderSection(modKey))}
    </div>
  );
};

export default ResumeColor;
