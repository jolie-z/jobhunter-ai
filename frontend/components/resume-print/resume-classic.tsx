import React from 'react';
import ReactMarkdown from 'react-markdown';
import { Mail, Phone, MapPin, Globe, Linkedin, Github } from 'lucide-react';
import { ResumeDataV2 } from '@/types/resume';
import { stripConfidenceTags } from '@/lib/utils/text-formatters';
import baseStyles from './styles/_base.module.css';
import styles from './styles/classic.module.css';

interface ResumeClassicProps {
  data: ResumeDataV2 & { avatar_url?: string | null };
}

export const ResumeClassic: React.FC<ResumeClassicProps> = ({ data }) => {
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

  // Helper function to render contact details
  const renderContactDetail = (label: string, value?: string | null, hrefPrefix: string = '') => {
    if (!value) return null;

    let finalHrefPrefix = hrefPrefix;
    if (
      ['Website', 'LinkedIn', 'GitHub'].includes(label) &&
      !value.startsWith('http') &&
      !value.startsWith('//')
    ) {
      finalHrefPrefix = 'https://';
    }

    const href = finalHrefPrefix + value;
    const isLink =
      finalHrefPrefix.startsWith('http') ||
      finalHrefPrefix.startsWith('mailto:') ||
      finalHrefPrefix.startsWith('tel:');

    let displayText = value;
    if (isLink && (label === 'LinkedIn' || label === 'GitHub' || label === 'Website')) {
      displayText = value.replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/$/, '');
    }

    return (
      <span className="inline-flex items-center gap-1">
        {isLink ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className={`${baseStyles['resume-link']} hover:underline`}
          >
            {displayText}
          </a>
        ) : (
          <span style={{ color: 'var(--resume-text-primary)' }}>{displayText}</span>
        )}
      </span>
    );
  };

  const renderSection = (modKey: string) => {
    const title = moduleTitles[modKey] || modKey;

    switch (modKey) {
      case 'summary':
        if (!summary) return null;
        return (
          <div key={modKey} className={baseStyles['resume-section']}>
            <h3 className={baseStyles['resume-section-title']}>{title}</h3>
            <div className={`text-justify ${baseStyles['resume-text']} ${baseStyles['resume-markdown']}`}>
              <ReactMarkdown components={{ p: ({node, ...props}) => <span className="block" {...props} /> }}>
                {stripConfidenceTags(summary)}
              </ReactMarkdown>
            </div>
          </div>
        );

      case 'workExperience':
        if (!workExperience || workExperience.length === 0) return null;
        return (
          <div key={modKey} className={baseStyles['resume-section']}>
            <h3 className={baseStyles['resume-section-title']}>{title}</h3>
            <div className={baseStyles['resume-items']}>
              {workExperience.map((exp, idx) => (
                <div key={idx} className={baseStyles['resume-item']}>
                  <div className={`grid grid-cols-[1fr_auto_1fr] items-baseline ${baseStyles['resume-row-tight']}`}>
                    <h4 className={`${baseStyles['resume-item-title']} text-left`}>
                      {exp.company}
                    </h4>
                    <h4 className={`${baseStyles['resume-item-title']} font-normal text-center px-4`}>
                      {exp.title}
                    </h4>
                    <span className={`${baseStyles['resume-date']} text-right`}>
                      {exp.years}
                    </span>
                  </div>
                  {exp.location && (
                    <div className={`flex justify-between items-center ${baseStyles['resume-row']} ${baseStyles['resume-item-subtitle']}`}>
                      <span></span>
                      <span>{exp.location}</span>
                    </div>
                  )}
                  {exp.description && exp.description.length > 0 && (
                    <div className={`mt-2 ${baseStyles['resume-text-sm']} ${baseStyles['resume-markdown']}`}>
                      <ReactMarkdown components={{ p: ({node, ...props}) => <span className="block" {...props} /> }}>
                        {stripConfidenceTags(exp.description.join('\n'))}
                      </ReactMarkdown>
                    </div>
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
            <h3 className={baseStyles['resume-section-title']}>{title}</h3>
            <div className={baseStyles['resume-items']}>
              {personalProjects.map((project, idx) => (
                <div key={idx} className={baseStyles['resume-item']}>
                  <div className={`grid grid-cols-[1fr_auto_1fr] items-baseline ${baseStyles['resume-row-tight']}`}>
                    <h4 className={`${baseStyles['resume-item-title']} text-left`}>
                      {project.name}
                    </h4>
                    <h4 className={`${baseStyles['resume-item-title']} font-normal text-center px-4`}>
                      {project.role}
                    </h4>
                    <span className={`${baseStyles['resume-date']} text-right`}>
                      {project.years}
                    </span>
                  </div>
                  {project.description && project.description.length > 0 && (
                    <div className={`mt-2 ${baseStyles['resume-text-sm']} ${baseStyles['resume-markdown']}`}>
                      <ReactMarkdown components={{ p: ({node, ...props}) => <span className="block" {...props} /> }}>
                        {stripConfidenceTags(project.description.join('\n'))}
                      </ReactMarkdown>
                    </div>
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
            <h3 className={baseStyles['resume-section-title']}>{title}</h3>
            <div className={baseStyles['resume-items']}>
              {education.map((edu, idx) => (
                <div key={idx} className={baseStyles['resume-item']}>
                  <div className={`grid grid-cols-[1fr_auto_1fr] items-baseline ${baseStyles['resume-row-tight']}`}>
                    <h4 className={`${baseStyles['resume-item-title']} text-left`}>
                      {edu.institution}
                    </h4>
                    <h4 className={`${baseStyles['resume-item-title']} font-normal text-center px-4`}>
                      {edu.major ? `${edu.major} · ${edu.degree}` : edu.degree}
                    </h4>
                    <span className={`${baseStyles['resume-date']} text-right`}>
                      {edu.years}
                    </span>
                  </div>
                  {edu.description && (
                    <div className={baseStyles['resume-text-sm']}>
                      <ReactMarkdown>{stripConfidenceTags(edu.description)}</ReactMarkdown>
                    </div>
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
            <h3 className={baseStyles['resume-section-title']}>{title}</h3>
            <div className={`text-justify ${baseStyles['resume-text-sm']} ${baseStyles['resume-markdown']}`}>
              {technicalSkills.length > 0 && (
                <ReactMarkdown components={{ p: ({node, ...props}) => <span className="block" {...props} /> }}>
                  {stripConfidenceTags(technicalSkills.join('\n'))}
                </ReactMarkdown>
              )}
              {languages.length > 0 && (
                <div className="mt-1">
                  <strong>语言：</strong>{languages.join(' / ')}
                </div>
              )}
              {certificationsTraining.length > 0 && (
                <div className="mt-1">
                  <strong>证书与培训：</strong>{certificationsTraining.join(' / ')}
                </div>
              )}
            </div>
          </div>
        );

      default:
        // Handle custom modules
        const customItems = customModules?.[modKey];
        if (!customItems || customItems.length === 0) return null;
        
        return (
          <div key={modKey} className={baseStyles['resume-section']}>
            <h3 className={baseStyles['resume-section-title']}>{title}</h3>
            <div className={baseStyles['resume-items']}>
              {customItems.map((item, idx) => (
                <div key={idx} className={baseStyles['resume-item']}>
                  <div className={`grid grid-cols-[1fr_auto_1fr] items-baseline ${baseStyles['resume-row-tight']}`}>
                    <h4 className={`${baseStyles['resume-item-title']} text-left`}>
                      {item.company || ""}
                    </h4>
                    <h4 className={`${baseStyles['resume-item-title']} font-normal text-center px-4`}>
                      {item.title || ""}
                    </h4>
                    <span className={`${baseStyles['resume-date']} text-right`}>
                      {item.years}
                    </span>
                  </div>
                  {item.location && (
                    <div className={`flex justify-between items-center ${baseStyles['resume-row']} ${baseStyles['resume-item-subtitle']}`}>
                      <span></span>
                      <span>{item.location}</span>
                    </div>
                  )}
                  {item.description && item.description.length > 0 && (
                    <div className={`mt-2 ${baseStyles['resume-text-sm']} ${baseStyles['resume-markdown']}`}>
                      <ReactMarkdown components={{ p: ({node, ...props}) => <span className="block" {...props} /> }}>
                        {stripConfidenceTags(item.description.join('\n'))}
                      </ReactMarkdown>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        );
    }
  };

  return (
    <div className={`${styles.container} ${baseStyles['resume-body']} bg-white text-black`}>
      {/* Header Section */}
      {personalInfo && (
        <header className={`${baseStyles['resume-header']}`}>
          {/* Avatar floating right - only rendered when avatar_url exists */}
          {(data.personalInfo?.avatar_url || data.avatar_url) && (
            <div className="absolute right-0 top-0 w-[75px] h-[100px] overflow-hidden bg-gray-100 rounded border border-gray-200 shadow-sm">
              <img src={(data.personalInfo?.avatar_url || data.avatar_url) as string} alt="Avatar" className="w-full h-full object-cover" />
            </div>
          )}

          {/* 当有照片时，为文字区域预留左右空间，确保文字绝对居中 */}
          <div style={(data.personalInfo?.avatar_url || data.avatar_url) ? { padding: '0 90px' } : undefined}>
            {personalInfo.name && (
              <h1 className={`${baseStyles['resume-name']} mb-2`}>
                {/^[\u4e00-\u9fa5]{2,4}$/.test(personalInfo.name.replace(/\s+/g, '')) 
                  ? personalInfo.name.replace(/\s+/g, '').split('').join(' ') 
                  : personalInfo.name}
              </h1>
            )}

            <div className={`flex flex-wrap justify-center items-center gap-y-1 ${baseStyles['resume-meta']} mb-1`}>
              {(() => {
                const items: React.ReactNode[] = [];
                const { name, title, ...rest } = personalInfo; // exclude name and title
                
                const addMeta = (key: string, value: any) => {
                   if (!value) return;
                   let prefix = '';
                   let hrefPrefix = '';
                   let isLink = false;

                   if (key === 'phone') {
                     hrefPrefix = 'tel:';
                     isLink = true;
                   } else if (key === 'email') {
                     hrefPrefix = 'mailto:';
                     isLink = true;
                   } else {
                     prefix = `${key}: `;
                     const strVal = String(value);
                     if (strVal.includes('http') || strVal.includes('github') || strVal.includes('www.')) {
                       if (!strVal.startsWith('http') && !strVal.startsWith('//')) {
                         hrefPrefix = 'https://';
                       }
                       isLink = true;
                     }
                   }

                   let displayText = String(value);
                   if (isLink && (key === 'website' || key.toLowerCase().includes('github') || key.toLowerCase().includes('linkedin') || key === '个人主页')) {
                     displayText = displayText.replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/$/, '');
                   }

                   items.push(
                     <span key={key} className="inline-flex items-center">
                       {prefix && <span style={{ color: 'var(--resume-text-primary)' }} className="mr-1">{prefix}</span>}
                       {isLink ? (
                         <a href={hrefPrefix + String(value)} target="_blank" rel="noopener noreferrer" className={`${baseStyles['resume-link']} hover:underline`}>
                           {displayText}
                         </a>
                       ) : (
                         <span style={{ color: 'var(--resume-text-primary)' }}>{displayText}</span>
                       )}
                     </span>
                   );
                };

                if (rest.phone) addMeta('phone', rest.phone);
                if (rest.email) addMeta('email', rest.email);
                if (rest.location) addMeta('所在城市', rest.location);
                if (rest.website) addMeta('个人主页', rest.website);
                
                Object.entries(rest).forEach(([k, v]) => {
                  if (['phone', 'email', 'location', 'website', 'avatar_url'].includes(k)) return;
                  addMeta(k, v);
                });

                return items.map((item, idx) => (
                  <React.Fragment key={idx}>
                    {idx > 0 && <span style={{ color: 'var(--resume-text-muted)', opacity: 0.5 }} className="mx-1">丨</span>}
                    {item}
                  </React.Fragment>
                ));
              })()}
            </div>

            {personalInfo.title && (
              <h2 className={`${baseStyles['resume-title']} ${baseStyles['resume-meta']} pb-2 text-center`}>
                <span style={{ color: 'var(--resume-text-primary)' }} className="mr-1">求职意向:</span>
                <span style={{ color: 'var(--resume-text-primary)' }}>{personalInfo.title}</span>
              </h2>
            )}
          </div>
        </header>
      )}

      {/* Render sections based on moduleOrder (deduplicated to avoid duplicate React keys) */}
      {[...new Set(moduleOrder)].map(modKey => renderSection(modKey))}
    </div>
  );
};

export default ResumeClassic;
