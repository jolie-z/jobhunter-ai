import React from 'react';
import { ResumeDataV2 } from '@/types/resume';
import ResumeClassic from '@/components/resume-print/resume-classic';
import ResumeColor from '@/components/resume-print/resume-color';
import ResumeColorV2 from '@/components/resume-print/resume-color-v2';
import { API_BASE } from '@/lib/api';

type PageProps = {
  searchParams: Promise<{
    record_id?: string;
    source?: string;
    preview_id?: string;
    template?: string;
  }>;
};

// Disable standard Next.js layouts for the print page
export const dynamic = 'force-dynamic';

async function fetchResumeData(recordId?: string, source?: string, previewId?: string): Promise<ResumeDataV2> {
  let url;
  if (previewId) {
    url = new URL(`${API_BASE}/api/strategy/preview-data/${encodeURIComponent(previewId)}`);
  } else if (recordId) {
    url = new URL(`${API_BASE}/api/strategy/resume-data/${encodeURIComponent(recordId)}`);
    if (source) {
      url.searchParams.append('source', source);
    }
  } else {
    throw new Error('Missing record_id or preview_id');
  }

  const res = await fetch(url.toString(), {
    cache: 'no-store',
  });
  
  if (!res.ok) {
    throw new Error(`Failed to load resume (status ${res.status}).`);
  }
  
  const payload = await res.json();
  return payload.data as ResumeDataV2;
}

export default async function PrintResumePage({ searchParams }: PageProps) {
  const resolvedParams = await searchParams;
  const recordId = resolvedParams.record_id;
  const source = resolvedParams.source;
  const previewId = resolvedParams.preview_id;
  const rawTemplate = resolvedParams.template;
  const template = rawTemplate === 'color_v2' ? 'color_v2' : rawTemplate === 'color' ? 'color' : 'classic';

  if (!recordId && !previewId) {
    return <div className="p-8 text-red-500">Error: Missing record_id or preview_id parameter</div>;
  }

  try {
    const resumeData = await fetchResumeData(recordId, source, previewId);
    let ResumeSkin = ResumeClassic;
    if (template === 'color_v2') {
      ResumeSkin = ResumeColorV2;
    } else if (template === 'color') {
      ResumeSkin = ResumeColor;
    }

    return (
      <div className="resume-print bg-white min-h-screen">
        <ResumeSkin data={resumeData} />
      </div>
    );
  } catch (error) {
    return (
      <div className="resume-print resume-error p-8 text-rose-500 bg-white min-h-screen">
        <h1 className="text-base font-bold">Failed to load resume data</h1>
        <p className="text-xs text-zinc-500 mt-1">{error instanceof Error ? error.message : 'Unknown error'}</p>
      </div>
    );
  }
}
