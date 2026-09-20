import { create } from 'zustand'
import type { 
  ResumeDataV2, 
  PersonalInfoV2, 
  ExperienceV2, 
  EducationV2, 
  ProjectV2, 
  AdditionalInfoV2 
} from '@/types/resume'

interface ResumeV2State {
  resumeData: ResumeDataV2 | null
  
  // Base setters
  setResumeData: (data: ResumeDataV2 | null) => void
  
  // Personal Info
  updatePersonalInfo: (data: Partial<PersonalInfoV2>) => void
  
  // Summary
  updateSummary: (summary: string) => void
  
  // Work Experience
  addWorkExperience: (exp: ExperienceV2) => void
  updateWorkExperience: (index: number, exp: Partial<ExperienceV2>) => void
  removeWorkExperience: (index: number) => void
  reorderWorkExperience: (startIndex: number, endIndex: number) => void
  archiveWorkExperience: (index: number) => void
  restoreWorkExperience: (index: number) => void

  // Education
  addEducation: (edu: EducationV2) => void
  updateEducation: (index: number, edu: Partial<EducationV2>) => void
  removeEducation: (index: number) => void
  reorderEducation: (startIndex: number, endIndex: number) => void

  // Projects
  addProject: (proj: ProjectV2) => void
  updateProject: (index: number, proj: Partial<ProjectV2>) => void
  removeProject: (index: number) => void
  reorderProject: (startIndex: number, endIndex: number) => void
  archiveProject: (index: number) => void
  restoreProject: (index: number) => void

  // Additional
  updateAdditional: (data: Partial<AdditionalInfoV2>) => void

  // Module Management
  moveModuleUp: (moduleKey: string) => void
  moveModuleDown: (moduleKey: string) => void
  addModule: (moduleKey: string) => void
  removeModule: (moduleKey: string) => void
  addCustomModule: (title: string) => void
  updateModuleTitle: (moduleKey: string, newTitle: string) => void

  // Custom Module Items Management
  addCustomItem: (moduleKey: string, item: ExperienceV2) => void
  updateCustomItem: (moduleKey: string, index: number, item: Partial<ExperienceV2>) => void
  removeCustomItem: (moduleKey: string, index: number) => void
  reorderCustomItem: (moduleKey: string, startIndex: number, endIndex: number) => void
}

const emptyResume: ResumeDataV2 = {
  personalInfo: {
    name: '',
    title: '',
    email: '',
    phone: '',
    location: '',
  },
  summary: '',
  workExperience: [],
  education: [],
  personalProjects: [],
  additional: {
    technicalSkills: [],
    languages: [],
    certificationsTraining: []
  },
  moduleOrder: ["summary", "additional", "workExperience", "personalProjects", "education"],
  moduleTitles: {
    "summary": "个人总结",
    "additional": "专业技能",
    "workExperience": "工作经历",
    "personalProjects": "项目经历",
    "education": "教育背景"
  },
  customModules: {}
}

// 每次调用返回全新对象（嵌套结构也重建）。切换简历需要重置画布时必须用它，
// 直接复用 emptyResume 常量会让多份简历共享同一份嵌套引用
export function createEmptyResume(): ResumeDataV2 {
  return {
    ...emptyResume,
    personalInfo: { ...emptyResume.personalInfo },
    workExperience: [],
    education: [],
    personalProjects: [],
    additional: { ...emptyResume.additional },
    moduleOrder: [...emptyResume.moduleOrder],
    moduleTitles: { ...emptyResume.moduleTitles },
    customModules: {},
  }
}

let _itemKeyCounter = 0
const genItemKey = () => `itm_${Date.now().toString(36)}_${++_itemKeyCounter}`

// 为经历条目注入稳定 _key（渲染层用它当 React key）。
// 下标 key 在删除/排序中间项时会让输入焦点与内容错位；
// _key 随结构化数据持久化，缺了才补，保证跨会话稳定
const withKeys = <T extends { _key?: string }>(items?: (T | null | undefined)[]): T[] =>
  ((items || []).filter(Boolean) as T[]).map(it => ({ ...it, _key: it._key || genItemKey() }))

export const useResumeV2Store = create<ResumeV2State>((set) => ({
  resumeData: null,

  setResumeData: (data) => set({
    resumeData: data ? {
      ...data,
      workExperience: withKeys(data.workExperience),
      personalProjects: withKeys(data.personalProjects),
      archivedProjects: withKeys(data.archivedProjects),
      archivedWorkExperience: withKeys(data.archivedWorkExperience),
      education: data.education ? withKeys(data.education) : data.education,
      moduleOrder: [...new Set(data.moduleOrder || [])],
    } : data
  }),

  updatePersonalInfo: (data) => 
    set((state) => {
      if (!state.resumeData) return state;
      return {
        resumeData: {
          ...state.resumeData,
          personalInfo: { ...state.resumeData.personalInfo, ...data }
        }
      }
    }),

  updateSummary: (summary) =>
    set((state) => {
      if (!state.resumeData) return state;
      return {
        resumeData: { ...state.resumeData, summary }
      }
    }),

  addWorkExperience: (exp) =>
    set((state) => {
      if (!state.resumeData) return state;
      return {
        resumeData: {
          ...state.resumeData,
          workExperience: [...state.resumeData.workExperience, { ...exp, _key: genItemKey() }]
        }
      }
    }),

  updateWorkExperience: (index, exp) =>
    set((state) => {
      if (!state.resumeData) return state;
      const newExp = [...state.resumeData.workExperience];
      newExp[index] = { ...newExp[index], ...exp };
      return {
        resumeData: { ...state.resumeData, workExperience: newExp }
      }
    }),

  removeWorkExperience: (index) =>
    set((state) => {
      if (!state.resumeData) return state;
      const newExp = [...state.resumeData.workExperience];
      newExp.splice(index, 1);
      return {
        resumeData: { ...state.resumeData, workExperience: newExp }
      }
    }),

  reorderWorkExperience: (startIndex, endIndex) =>
    set((state) => {
      if (!state.resumeData) return state;
      const result = Array.from(state.resumeData.workExperience);
      const [removed] = result.splice(startIndex, 1);
      result.splice(endIndex, 0, removed);
      return {
        resumeData: { ...state.resumeData, workExperience: result }
      }
    }),

  archiveWorkExperience: (index) =>
    set((state) => {
      if (!state.resumeData) return state;
      const newExp = [...state.resumeData.workExperience];
      const archived = [...(state.resumeData.archivedWorkExperience || [])].filter(Boolean);
      const [removed] = newExp.splice(index, 1);
      if (removed) archived.push(removed);
      return {
        resumeData: { ...state.resumeData, workExperience: newExp, archivedWorkExperience: archived }
      }
    }),

  restoreWorkExperience: (index) =>
    set((state) => {
      if (!state.resumeData) return state;
      const newExp = [...state.resumeData.workExperience].filter(Boolean);
      const archived = [...(state.resumeData.archivedWorkExperience || [])].filter(Boolean);
      const [restored] = archived.splice(index, 1);
      if (restored) newExp.push(restored);
      return {
        resumeData: { ...state.resumeData, workExperience: newExp, archivedWorkExperience: archived }
      }
    }),

  addEducation: (edu) =>
    set((state) => {
      if (!state.resumeData) return state;
      return {
        resumeData: {
          ...state.resumeData,
          education: [...state.resumeData.education, { ...edu, _key: genItemKey() }]
        }
      }
    }),

  updateEducation: (index, edu) =>
    set((state) => {
      if (!state.resumeData) return state;
      const newEdu = [...state.resumeData.education];
      newEdu[index] = { ...newEdu[index], ...edu };
      return {
        resumeData: { ...state.resumeData, education: newEdu }
      }
    }),

  removeEducation: (index) =>
    set((state) => {
      if (!state.resumeData) return state;
      const newEdu = [...state.resumeData.education];
      newEdu.splice(index, 1);
      return {
        resumeData: { ...state.resumeData, education: newEdu }
      }
    }),

  reorderEducation: (startIndex, endIndex) =>
    set((state) => {
      if (!state.resumeData) return state;
      const result = Array.from(state.resumeData.education);
      const [removed] = result.splice(startIndex, 1);
      result.splice(endIndex, 0, removed);
      return {
        resumeData: { ...state.resumeData, education: result }
      }
    }),

  addProject: (proj) =>
    set((state) => {
      if (!state.resumeData) return state;
      return {
        resumeData: {
          ...state.resumeData,
          personalProjects: [...state.resumeData.personalProjects, { ...proj, _key: genItemKey() }]
        }
      }
    }),

  updateProject: (index, proj) =>
    set((state) => {
      if (!state.resumeData) return state;
      const newProj = [...state.resumeData.personalProjects];
      newProj[index] = { ...newProj[index], ...proj };
      return {
        resumeData: { ...state.resumeData, personalProjects: newProj }
      }
    }),

  removeProject: (index) =>
    set((state) => {
      if (!state.resumeData) return state;
      const newProj = [...state.resumeData.personalProjects];
      newProj.splice(index, 1);
      return {
        resumeData: { ...state.resumeData, personalProjects: newProj }
      }
    }),

  reorderProject: (startIndex, endIndex) =>
    set((state) => {
      if (!state.resumeData) return state;
      const result = Array.from(state.resumeData.personalProjects);
      const [removed] = result.splice(startIndex, 1);
      result.splice(endIndex, 0, removed);
      return {
        resumeData: { ...state.resumeData, personalProjects: result }
      }
    }),

  archiveProject: (index) =>
    set((state) => {
      if (!state.resumeData) return state;
      const newProj = [...state.resumeData.personalProjects];
      const archived = [...(state.resumeData.archivedProjects || [])].filter(Boolean);
      const [removed] = newProj.splice(index, 1);
      if (removed) archived.push(removed);
      return {
        resumeData: { ...state.resumeData, personalProjects: newProj, archivedProjects: archived }
      }
    }),

  restoreProject: (index) =>
    set((state) => {
      if (!state.resumeData) return state;
      const newProj = [...state.resumeData.personalProjects].filter(Boolean);
      const archived = [...(state.resumeData.archivedProjects || [])].filter(Boolean);
      const [restored] = archived.splice(index, 1);
      if (restored) newProj.push(restored);
      return {
        resumeData: { ...state.resumeData, personalProjects: newProj, archivedProjects: archived }
      }
    }),

  updateAdditional: (data) =>
    set((state) => {
      if (!state.resumeData) return state;
      return {
        resumeData: {
          ...state.resumeData,
          additional: { ...state.resumeData.additional, ...data }
        }
      }
    }),

  moveModuleUp: (moduleKey) =>
    set((state) => {
      if (!state.resumeData) return state;
      const order = [...state.resumeData.moduleOrder];
      const idx = order.indexOf(moduleKey);
      if (idx > 0) {
        [order[idx - 1], order[idx]] = [order[idx], order[idx - 1]];
      }
      return { resumeData: { ...state.resumeData, moduleOrder: order } };
    }),

  moveModuleDown: (moduleKey) =>
    set((state) => {
      if (!state.resumeData) return state;
      const order = [...state.resumeData.moduleOrder];
      const idx = order.indexOf(moduleKey);
      if (idx !== -1 && idx < order.length - 1) {
        [order[idx + 1], order[idx]] = [order[idx], order[idx + 1]];
      }
      return { resumeData: { ...state.resumeData, moduleOrder: order } };
    }),

  addModule: (moduleKey) =>
    set((state) => {
      if (!state.resumeData) return state;
      const order = [...state.resumeData.moduleOrder];
      if (!order.includes(moduleKey)) {
        order.push(moduleKey);
      }
      return { resumeData: { ...state.resumeData, moduleOrder: order } };
    }),

  removeModule: (moduleKey) =>
    set((state) => {
      if (!state.resumeData) return state;
      const order = state.resumeData.moduleOrder.filter(k => k !== moduleKey);
      
      // Clean up custom modules data when removing a custom module
      const customModules = { ...state.resumeData.customModules };
      if (customModules[moduleKey]) {
        delete customModules[moduleKey];
      }
      
      // Clean up custom module titles to keep state clean
      const moduleTitles = { ...state.resumeData.moduleTitles };
      if (moduleKey.startsWith('custom_')) {
        delete moduleTitles[moduleKey];
      }

      return { 
        resumeData: { 
          ...state.resumeData, 
          moduleOrder: order,
          customModules,
          moduleTitles
        } 
      };
    }),

  addCustomModule: (title) =>
    set((state) => {
      if (!state.resumeData) return state;
      // Generate a unique key for the custom module
      const key = `custom_${Date.now()}`;
      const order = [...state.resumeData.moduleOrder, key];
      const titles = { ...state.resumeData.moduleTitles, [key]: title };
      const customModules = { ...state.resumeData.customModules, [key]: [] };
      return {
        resumeData: {
          ...state.resumeData,
          moduleOrder: order,
          moduleTitles: titles,
          customModules: customModules
        }
      };
    }),

  updateModuleTitle: (moduleKey, newTitle) =>
    set((state) => {
      if (!state.resumeData) return state;
      const titles = { ...state.resumeData.moduleTitles, [moduleKey]: newTitle };
      return { resumeData: { ...state.resumeData, moduleTitles: titles } };
    }),

  addCustomItem: (moduleKey, item) =>
    set((state) => {
      if (!state.resumeData) return state;
      const customModules = { ...state.resumeData.customModules };
      const currentList = customModules[moduleKey] || [];
      customModules[moduleKey] = [...currentList, { ...item, _key: genItemKey() }];
      return { resumeData: { ...state.resumeData, customModules } };
    }),

  updateCustomItem: (moduleKey, index, item) =>
    set((state) => {
      if (!state.resumeData) return state;
      const customModules = { ...state.resumeData.customModules };
      const currentList = [...(customModules[moduleKey] || [])];
      currentList[index] = { ...currentList[index], ...item };
      customModules[moduleKey] = currentList;
      return { resumeData: { ...state.resumeData, customModules } };
    }),

  removeCustomItem: (moduleKey, index) =>
    set((state) => {
      if (!state.resumeData) return state;
      const customModules = { ...state.resumeData.customModules };
      const currentList = [...(customModules[moduleKey] || [])];
      currentList.splice(index, 1);
      customModules[moduleKey] = currentList;
      return { resumeData: { ...state.resumeData, customModules } };
    }),

  reorderCustomItem: (moduleKey, startIndex, endIndex) =>
    set((state) => {
      if (!state.resumeData) return state;
      const customModules = { ...state.resumeData.customModules };
      const currentList = [...(customModules[moduleKey] || [])];
      const [removed] = currentList.splice(startIndex, 1);
      currentList.splice(endIndex, 0, removed);
      customModules[moduleKey] = currentList;
      return { resumeData: { ...state.resumeData, customModules } };
    })
}));
