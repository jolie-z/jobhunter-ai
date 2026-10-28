import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { useResumeV2Store, createEmptyResume } from "@/hooks/use-resume-v2-store"
import type { ResumeDataV2, ExperienceV2, EducationV2 } from "@/types/resume"

// 定制面板「未保存提醒」脏检测契约：dirty = JSON.stringify(store.resumeData) !== savedBaseline。
// 装载必须用 setResumeDataWithBaseline（同事务、转换后形态做基线）。
// 2026-10-19 误报根因：job-detail-workspace 装载时用 setResumeData（注入 _key）写 store、
// 却用未注入 _key 的原始对象 stringify 做基线，来源 JSON 不含 _key 时装载即恒 dirty。

const isDirty = () => {
  const { resumeData, savedBaseline } = useResumeV2Store.getState()
  return Boolean(resumeData) && JSON.stringify(resumeData) !== savedBaseline
}

// 模拟后端/LLM 产出的简历 JSON：条目天然不含客户端合成字段 _key
const buildRawResume = (): ResumeDataV2 => {
  const raw = createEmptyResume()
  raw.personalInfo.name = "候选人X"
  raw.workExperience = [
    { company: "公司A", position: "岗位T", bullets: [] } as unknown as ExperienceV2,
  ]
  raw.education = [{ school: "学校B" } as unknown as EducationV2]
  raw.moduleOrder = ["workExperience", "education"]
  return raw
}

describe("useResumeV2Store 脏检测基线契约（定制面板未保存提醒）", () => {
  const resetStore = () => {
    useResumeV2Store.getState().setResumeData(null)
    useResumeV2Store.getState().setSavedBaseline("")
  }
  beforeEach(resetStore)
  afterEach(resetStore)

  it("装载走 setResumeDataWithBaseline：来源 JSON 不含 _key 时装载后不脏", () => {
    useResumeV2Store.getState().setResumeDataWithBaseline(buildRawResume())
    const { resumeData, savedBaseline } = useResumeV2Store.getState()
    expect(resumeData?.workExperience[0]._key).toMatch(/^itm_/)
    expect(savedBaseline).toBe(JSON.stringify(resumeData))
    expect(isDirty()).toBe(false)
  })

  it("反例固化：setResumeData + 原始对象做基线 → 装载即恒 dirty（禁止在装载路径使用）", () => {
    const raw = buildRawResume()
    useResumeV2Store.getState().setResumeData(raw)
    useResumeV2Store.getState().setSavedBaseline(JSON.stringify(raw))
    expect(isDirty()).toBe(true)
  })

  it("装载后真实编辑仍能被检出为脏", () => {
    useResumeV2Store.getState().setResumeDataWithBaseline(buildRawResume())
    expect(isDirty()).toBe(false)
    useResumeV2Store.getState().updatePersonalInfo({ name: "候选人Y" })
    expect(isDirty()).toBe(true)
  })

  it("已保存过（JSON 已含 _key）的简历再次装载不脏且 _key 保持稳定", () => {
    useResumeV2Store.getState().setResumeDataWithBaseline(buildRawResume())
    const savedByApp = JSON.parse(JSON.stringify(useResumeV2Store.getState().resumeData)) as ResumeDataV2
    const keyBefore = savedByApp.workExperience[0]._key

    useResumeV2Store.getState().setResumeDataWithBaseline(savedByApp)
    expect(isDirty()).toBe(false)
    expect(useResumeV2Store.getState().resumeData?.workExperience[0]._key).toBe(keyBefore)
  })

  it("卸载清空后 resumeData 为 null、基线为空，均不构成脏", () => {
    useResumeV2Store.getState().setResumeDataWithBaseline(buildRawResume())
    useResumeV2Store.getState().setResumeData(null)
    useResumeV2Store.getState().setSavedBaseline("")
    const { resumeData, savedBaseline } = useResumeV2Store.getState()
    expect(resumeData).toBeNull()
    expect(savedBaseline).toBe("")
    expect(isDirty()).toBe(false)
  })
})
