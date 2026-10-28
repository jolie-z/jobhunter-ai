import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { SkillPreflightDialog } from './skill-preflight-dialog'
import type { SkillPreflightReport } from '@/hooks/use-skill-rewrite'

const report: SkillPreflightReport = {
  skill_id: 'custom_cover',
  engine: 'agent',
  result_kind: 'markdown',
  has_resume_output: false,
  expected_artifact_count: 2,
  final_artifact: '02_cover_letter.md',
  final_source: 'final_marker',
  outputs: [
    { filename: '01_analysis.md', kind: 'markdown', is_final: false, is_resume: false },
    { filename: '02_cover_letter.md', kind: 'markdown', is_final: true, is_resume: false },
  ],
  output_count_source: 'skill_md',
  warnings: ['未检测到简历改写产物：执行结果只归档到产物库，不会写回简历库。'],
  will_load: {
    skill_md: true,
    skill_chars: 1200,
    references_count: 3,
    jd_chars: 800,
    resume_chars: 2200,
    diagnosis_injected: true,
    resume_library_mode: false,
  },
  estimated_tokens: { point: 120000, low: 80000, high: 180000, source: 'heuristic' },
  estimate_scope: 'skill_and_inputs',
}

describe('SkillPreflightDialog 执行前预检', () => {
  it('展示产物数量/是否含简历/将加载上下文/token 预估与警告', () => {
    render(
      <SkillPreflightDialog
        open
        report={report}
        skillName="Cover Letter Writer"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )
    expect(screen.getByText(/执行前预检/)).toBeTruthy()
    expect(screen.getByText('2 份')).toBeTruthy()
    expect(screen.getByText('未检测到')).toBeTruthy()
    expect(screen.getByText('01_analysis.md')).toBeTruthy()
    expect(screen.getByText('02_cover_letter.md')).toBeTruthy()
    expect(screen.getByText(/80K ~ 180K/)).toBeTruthy()
    expect(screen.getByText(/不会写回简历库/)).toBeTruthy()
    expect(screen.getByText(/岗位 JD：800 字/)).toBeTruthy()
  })

  it('简历库模式把加载上下文标注为「A级岗位画像」而非岗位 JD', () => {
    render(
      <SkillPreflightDialog
        open
        report={{ ...report, will_load: { ...report.will_load, resume_library_mode: true } }}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )
    expect(screen.getByText(/A级岗位画像：800 字/)).toBeTruthy()
    expect(screen.queryByText(/岗位 JD/)).toBeFalsy()
    expect(screen.getByText(/选中的简历/)).toBeTruthy()
  })

  it('确认/取消分别回调，不自动执行', () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(
      <SkillPreflightDialog
        open
        report={report}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )
    fireEvent.click(screen.getByText('确认执行'))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByText('取消'))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('预检失败仍可确认执行', () => {
    const onConfirm = vi.fn()
    render(
      <SkillPreflightDialog
        open
        report={null}
        errorMessage="无法读取技能包"
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    )
    expect(screen.getByText(/预检失败/)).toBeTruthy()
    expect(screen.getByText(/无法读取技能包/)).toBeTruthy()
    fireEvent.click(screen.getByText('确认执行'))
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })
})
