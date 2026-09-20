import React from 'react';
import ReactMarkdown from 'react-markdown';
import { Mail, Phone, MapPin, Globe, Linkedin, Github } from 'lucide-react';
import { ResumeData } from '@/types/resume';
import { stripConfidenceTags } from '@/lib/utils/text-formatters';
import baseStyles from './styles/_base.module.css';
import styles from './styles/classic.module.css';

interface ResumeClassicMarkdownProps {
  data: ResumeData & { avatar_url?: string | null };
}

export const ResumeClassicMarkdown: React.FC<ResumeClassicMarkdownProps> = ({ data }) => {
  const { header, sections, avatar_url } = data;
  const parsedInfo = header?.parsedInfo;

  return (
    <div className={`${styles.container} ${baseStyles['resume-body']} bg-white text-black`}>
      {/* Header Section */}
      {(header || parsedInfo) && (
        <header className={`${baseStyles['resume-header']}`}>
          {/* Avatar floating right */}
          {((parsedInfo as any)?.avatar_url || avatar_url) && (
            <div className="absolute right-0 top-0 w-[90px] h-[120px] overflow-hidden bg-gray-100 rounded border border-gray-200 shadow-sm">
              <img src={((parsedInfo as any)?.avatar_url || avatar_url) as string} alt="Avatar" className="w-full h-full object-cover" />
            </div>
          )}

          <div style={((parsedInfo as any)?.avatar_url || avatar_url) ? { padding: '0 110px' } : undefined}>
            {header?.name && (
              <h1 className={`${baseStyles['resume-name']} mb-2`}>
                {/^[\u4e00-\u9fa5]{2,4}$/.test(header.name.replace(/\s+/g, ''))
                  ? header.name.replace(/\s+/g, '').split('').join(' ')
                  : header.name}
              </h1>
            )}

            {/* Contact Line */}
            {header?.contact && (
              <div className={`flex flex-wrap justify-center items-center gap-y-1 ${baseStyles['resume-meta']} mb-1`}>
                {(() => {
                  const parts = header.contact.split(/\||丨/).map(p => p.trim()).filter(Boolean);
                  return parts.map((part, idx) => {
                    let hrefPrefix = '';
                    let isLink = false;
                    const partLower = part.toLowerCase();

                    if (partLower.includes('phone') || partLower.includes('电话') || partLower.includes('手机') || /^1\d{10}$/.test(part)) {
                      hrefPrefix = 'tel:';
                      isLink = true;
                    } else if (partLower.includes('email') || partLower.includes('邮箱') || partLower.includes('@')) {
                      hrefPrefix = 'mailto:';
                      isLink = true;
                    }

                    const displayText = part;
                    let rawValue = part;
                    if (part.includes(':') || part.includes('：')) {
                      rawValue = part.split(/[:：]/)[1].trim();
                    }

                    if (isLink) {
                      return (
                        <React.Fragment key={idx}>
                          {idx > 0 && <span style={{ color: 'var(--resume-text-muted)', opacity: 0.5 }} className="mx-1">丨</span>}
                          <span className="inline-flex items-center">
                            <a href={hrefPrefix + rawValue} target="_blank" rel="noopener noreferrer" className={`${baseStyles['resume-link']} hover:underline`}>
                              {displayText}
                            </a>
                          </span>
                        </React.Fragment>
                      );
                    }

                    return (
                      <React.Fragment key={idx}>
                        {idx > 0 && <span style={{ color: 'var(--resume-text-muted)', opacity: 0.5 }} className="mx-1">丨</span>}
                        <span className="inline-flex items-center">
                          <span style={{ color: 'var(--resume-text-primary)' }}>{displayText}</span>
                        </span>
                      </React.Fragment>
                    );
                  });
                })()}
              </div>
            )}

            {/* Intention Line */}
            {header?.intention && (
              <div className={`flex flex-wrap justify-center items-center gap-y-1 ${baseStyles['resume-meta']} pb-2`}>
                {(() => {
                  const parts = header.intention.split(/\||丨/).map(p => p.trim()).filter(Boolean);
                  return parts.map((part, idx) => {
                    let hrefPrefix = '';
                    let isLink = false;
                    const partLower = part.toLowerCase();

                    if (partLower.includes('http') || partLower.includes('github') || partLower.includes('www.') || partLower.includes('主页') || partLower.includes('博客')) {
                      hrefPrefix = partLower.includes('http') ? '' : 'https://';
                      isLink = true;
                    }

                    let displayText = part;
                    let rawValue = part;
                    if (part.includes(':') || part.includes('：')) {
                      rawValue = part.substring(part.indexOf(':') !== -1 ? part.indexOf(':') + 1 : part.indexOf('：') + 1).trim();
                    }

                    if (isLink && (partLower.includes('website') || partLower.includes('github') || partLower.includes('linkedin') || partLower.includes('主页') || partLower.includes('博客'))) {
                      displayText = part.replace(rawValue, rawValue.replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/$/, ''));
                    }

                    // Add "求职意向:" prefix if it doesn't have one and it's the first part
                    if (idx === 0 && !displayText.includes(':') && !displayText.includes('：') && !displayText.includes('意向')) {
                       displayText = '求职意向: ' + displayText;
                    }

                    if (isLink) {
                      return (
                        <React.Fragment key={idx}>
                          {idx > 0 && <span style={{ color: 'var(--resume-text-muted)', opacity: 0.5 }} className="mx-1">丨</span>}
                          <span className="inline-flex items-center">
                            <a href={hrefPrefix + rawValue} target="_blank" rel="noopener noreferrer" className={`${baseStyles['resume-link']} hover:underline`}>
                              {displayText}
                            </a>
                          </span>
                        </React.Fragment>
                      );
                    }

                    return (
                      <React.Fragment key={idx}>
                        {idx > 0 && <span style={{ color: 'var(--resume-text-muted)', opacity: 0.5 }} className="mx-1">丨</span>}
                        <span className="inline-flex items-center">
                          <span style={{ color: 'var(--resume-text-primary)' }}>{displayText}</span>
                        </span>
                      </React.Fragment>
                    );
                  });
                })()}
              </div>
            )}
          </div>
        </header>
      )}

      {/* Render Markdown Sections */}
      {sections?.map((section) => {
        // level 1 implies top-level section
        // level 2 implies a sub-item (like a specific job or project)
        // Since markdown can be nested, we should handle them smoothly
        
        if (section.level === 1) {
          return (
            <div key={section.id} className={baseStyles['resume-section']}>
              <h3 className={baseStyles['resume-section-title']}>{section.title}</h3>
              <div className={`text-justify ${baseStyles['resume-text-sm']} ${baseStyles['resume-markdown']}`}>
                <ReactMarkdown components={{ p: ({node, ...props}) => <span className="block" {...props} /> }}>
                  {stripConfidenceTags(section.content)}
                </ReactMarkdown>
              </div>
            </div>
          );
        } else {
          return (
            <div key={section.id} className={`${baseStyles['resume-item']} pl-4 mt-2`}>
              <h4 className={`${baseStyles['resume-item-title']} font-bold mb-1`}>{section.title}</h4>
              <div className={`text-justify ${baseStyles['resume-text-sm']} ${baseStyles['resume-markdown']}`}>
                <ReactMarkdown components={{ p: ({node, ...props}) => <span className="block" {...props} /> }}>
                  {stripConfidenceTags(section.content)}
                </ReactMarkdown>
              </div>
            </div>
          );
        }
      })}
    </div>
  );
};

export default ResumeClassicMarkdown;
