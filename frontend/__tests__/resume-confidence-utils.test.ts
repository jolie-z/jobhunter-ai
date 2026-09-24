import { describe, it, expect } from "vitest"
import { getPendingModuleKeys } from "../components/dashboard/features/v2-resume-editor/utils/resume-confidence-utils"

describe("getPendingModuleKeys", () => {
  it("should return only low-confidence module keys", () => {
    const confidence = {
      summary: "low",
      workExperience: "high",
      personalProjects: "high",
      education: "low",
      additional: "confirmed",
    }
    expect(getPendingModuleKeys(confidence)).toEqual(["summary", "education"])
  })

  it("should return empty for confirmed/high-only or empty maps", () => {
    expect(getPendingModuleKeys({ summary: "confirmed" })).toEqual([])
    expect(getPendingModuleKeys({})).toEqual([])
  })

  it("should tolerate missing confidence map", () => {
    expect(getPendingModuleKeys(undefined)).toEqual([])
    expect(getPendingModuleKeys(null)).toEqual([])
  })
})
