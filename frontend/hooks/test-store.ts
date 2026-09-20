import { useResumeV2Store } from './use-resume-v2-store';

const store = useResumeV2Store.getState();
store.setResumeData({
  ...store.resumeData,
  personalProjects: [
    { name: 'Proj 1', description: 'desc 1' },
    { name: 'Proj 2', description: 'desc 2' },
    { name: 'Proj 3', description: 'desc 3' }
  ]
} as any);

const s1 = useResumeV2Store.getState();
console.log('initial:', s1.resumeData?.personalProjects);

s1.archiveProject(1); // archive Proj 2
const s2 = useResumeV2Store.getState();
console.log('after archive:', s2.resumeData?.personalProjects, s2.resumeData?.archivedProjects);

s2.restoreProject(0); // restore Proj 2
const s3 = useResumeV2Store.getState();
console.log('after restore:', s3.resumeData?.personalProjects, s3.resumeData?.archivedProjects);
