import React from 'react';
import { API_BASE } from '@/lib/api';
import { ResumeData, ResumeDataV2 } from '@/types/resume';
import { markdownToResumeData } from '@/lib/resume-converter';
import { mapApiItemToJob } from '@/lib/job-mapper';
import ResumeClassicMarkdown from '@/components/resume-print/resume-classic-markdown';
import ResumeClassic from '@/components/resume-print/resume-classic';
import ResumeColor from '@/components/resume-print/resume-color';
import ResumeColorV2 from '@/components/resume-print/resume-color-v2';


type PageProps = {
  searchParams: Promise<{
    job_id?: string;
    use_temp?: string;
    template?: string;
  }>;
};

export const dynamic = 'force-dynamic';

async function fetchJobResumeData(jobId: string): Promise<ResumeData | null> {
  try {
    // 🌟 列表接口已瘦身（不含AI改写JSON等大文本），改用单岗位详情接口按需获取
    const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/detail`, { cache: 'no-store' });
    if (!res.ok) {
      throw new Error(`Failed to load job detail (status ${res.status}).`);
    }
    const payload = await res.json();
    const job = payload?.data ? mapApiItemToJob(payload.data, 0) : null;

    if (!job || !job.manualRefinedResume) {
      return null;
    }

    return markdownToResumeData(job.manualRefinedResume);
  } catch (error) {
    console.error("Error fetching job resume data:", error);
    throw error;
  }
}

export default async function PrintJobResumePage({ searchParams }: PageProps) {
  const resolvedParams = await searchParams;
  const jobId = resolvedParams.job_id;
  const useTemp = resolvedParams.use_temp;
  const rawTemplate = resolvedParams.template;
  const template = rawTemplate === 'color_v2' ? 'color_v2' : rawTemplate === 'color' ? 'color' : 'classic';

  if (!jobId) {
    return <div className="p-8 text-red-500">Error: Missing job_id parameter</div>;
  }

  try {
    // 🌟 模式 A：无多Agent的结构化 JSON 链路 (通过临时存储通信)
    if (useTemp === '1') {
      const res = await fetch(`${API_BASE}/api/jobs/temp-data/${jobId}`, { cache: 'no-store' });
      if (!res.ok) {
        throw new Error(`Failed to load temp data (status ${res.status}).`);
      }
      const resumeDataV2: ResumeDataV2 = await res.json();
      let ResumeSkin = ResumeClassic;
      if (template === 'color_v2') {
        ResumeSkin = ResumeColorV2;
      } else if (template === 'color') {
        ResumeSkin = ResumeColor;
      }
      return (
        <div className="resume-print bg-white min-h-screen">
          <ResumeSkin data={resumeDataV2} />
        </div>
      );
    }
    
    // 🌟 模式 B：多Agent 或 兜底 Markdown 链路 (保证旧逻辑完好无损)
    else {
      const resumeData = await fetchJobResumeData(jobId);
      
      if (!resumeData) {
        return <div className="p-8 text-red-500">Error: Job not found or manual resume is empty.</div>;
      }

      return (
        <div className="resume-print bg-white min-h-screen">
          <ResumeClassicMarkdown data={resumeData} />
        </div>
      );
    }
  } catch (error) {
    return (
      <div className="p-8 text-red-500">
        <h1>Failed to load resume data</h1>
        <p>{error instanceof Error ? error.message : String(error)}</p>
      </div>
    );
  }
}
