import React from "react"
import { Building2, MapPin, Wallet, ExternalLink, Gauge, Sparkles, ThumbsUp, ThumbsDown, Briefcase, Users, Factory, GraduationCap, Activity, CalendarDays, Crown, UserRound, Send, Clock, Navigation } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import type { JobData } from "@/types/job"
import { splitTagString, formatDateMaybeTimestamp } from "@/lib/utils/text-formatters"
import { getStatusBadgeColor } from "../job-detail-workspace"
import { PlatformBadge } from "@/components/dashboard/platform-badge"
import { normalizePlatform } from "@/lib/job-data"

export function JobArchiveColumn({ job }: { job: JobData | null }) {
  if (!job) return null

  const status = job.followStatus || "新线索"
  const hrSkills = splitTagString(job.hrSkills)
  const benefits = splitTagString(job.benefits)
  const isHeadhunter = job.role === "猎头"

  return (
    <div className="flex h-full flex-col bg-card">
      {/* Sticky header */}
      <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-border bg-card/80 px-4 py-3 backdrop-blur-sm">
        <div className="flex min-w-0 items-center gap-2">
          <h2 className="truncate text-sm font-semibold tracking-tight text-foreground">岗位存档</h2>
        </div>
        <div className="flex items-center gap-2">
          <PlatformBadge platform={normalizePlatform(job.platform || "")} size="sm" />
          <Badge className={`shrink-0 rounded-full border-transparent px-2.5 py-0.5 text-xs font-medium ${getStatusBadgeColor(status)}`}>
            {status}
          </Badge>
        </div>
      </header>

      <ScrollArea className="min-h-0 flex-1">
        <div className="px-5 pb-8 pt-5">
          {/* Hero section */}
          <section>
            <h1 className="text-balance text-xl font-bold leading-snug tracking-tight text-foreground">
              {job.jobTitle || "未命名岗位"}
            </h1>

            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                <Building2 className="h-3.5 w-3.5" />
                {job.companyName || "-"}
              </span>
              <span className="text-border">·</span>
              <span className="inline-flex items-center gap-1.5">
                <MapPin className="h-3.5 w-3.5" />
                {job.location || "-"}
              </span>
            </div>

            <div className="mt-4 flex items-center gap-2">
              <Wallet className="h-5 w-5 text-orange-500" />
              <span className="text-2xl font-bold tracking-tight text-orange-500">
                {job.salary || "薪资面议"}
              </span>
            </div>

            {job.directLink && job.directLink !== "#" && (
              <Button
                asChild
                className="mt-4 h-10 w-full gap-2 rounded-lg text-sm font-medium"
              >
                <a href={job.directLink} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="h-4 w-4" />
                  打开岗位详情链接
                </a>
              </Button>
            )}
          </section>



          {/* Metadata grid */}
          <section className="mt-6">
            <SectionLabel icon={<Briefcase className="h-3.5 w-3.5" />} title="岗位信息" />
            <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border">
              <MetaCell icon={<Users className="h-3.5 w-3.5" />} label="公司规模" value={job.companyScale || "-"} />
              <MetaCell icon={<Factory className="h-3.5 w-3.5" />} label="所属行业" value={job.industry || "-"} />
              <MetaCell icon={<GraduationCap className="h-3.5 w-3.5" />} label="学历要求" value={job.education || "-"} />
              <MetaCell icon={<Briefcase className="h-3.5 w-3.5" />} label="经验要求" value={job.experience || "-"} />
              <MetaCell icon={<Activity className="h-3.5 w-3.5" />} label="HR活跃度" value={job.hrActivity || "-"} />
              <MetaCell
                icon={<CalendarDays className="h-3.5 w-3.5" />}
                label="发布日期"
                value={job.publishDate || "-"}
                valueClassName="text-blue-600"
              />
              <MetaCell
                icon={isHeadhunter ? <Crown className="h-3.5 w-3.5 text-orange-500" /> : <UserRound className="h-3.5 w-3.5" />}
                label="角色"
                value={job.role || "-"}
                valueClassName={isHeadhunter ? "text-orange-600 font-semibold" : "text-green-600"}
              />
              <MetaCell icon={<Send className="h-3.5 w-3.5" />} label="投递日期" value={formatDateMaybeTimestamp(job.applyDate) || "-"} />
              <MetaCell icon={<Clock className="h-3.5 w-3.5" />} label="抓取时间" value={formatDateMaybeTimestamp(job.captureTime) || "-"} />
              <MetaCell icon={<Navigation className="h-3.5 w-3.5" />} label="工作地址" value={job.workAddress || "-"} />
            </div>
          </section>

          {/* Tags */}
          {(hrSkills.length > 0 || benefits.length > 0) && (
            <section className="mt-6 space-y-4">
              {hrSkills.length > 0 && (
                <div>
                  <SectionLabel icon={<UserRound className="h-3.5 w-3.5" />} title="HR技能标签" />
                  <div className="flex flex-wrap gap-1.5">
                    {hrSkills.map((skill, index) => (
                      <span
                        key={`${skill}-${index}`}
                        className="rounded-md bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 ring-1 ring-inset ring-blue-100"
                      >
                        {skill}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {benefits.length > 0 && (
                <div>
                  <SectionLabel icon={<Sparkles className="h-3.5 w-3.5" />} title="福利标签" />
                  <div className="flex flex-wrap gap-1.5">
                    {benefits.map((benefit, index) => (
                      <span
                        key={`${benefit}-${index}`}
                        className="rounded-md bg-green-50 px-2.5 py-1 text-xs font-medium text-green-700 ring-1 ring-inset ring-green-100"
                      >
                        {benefit}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </section>
          )}

          {/* Job description */}
          <section className="mt-6">
            <SectionLabel icon={<Briefcase className="h-3.5 w-3.5" />} title="岗位详情" />
            <div className="rounded-xl border border-border bg-muted/50 p-4 text-sm leading-relaxed text-foreground/90 whitespace-pre-line">
              {job.jobDescription || "暂无岗位详情"}
            </div>
          </section>
        </div>
      </ScrollArea>
    </div>
  )
}

function SectionLabel({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="mb-2.5 flex items-center gap-1.5 text-muted-foreground">
      {icon}
      <h3 className="text-xs font-semibold uppercase tracking-wide">{title}</h3>
    </div>
  )
}

function ScoreCard({ icon, label, value, suffix, valueClassName = "" }: { icon: React.ReactNode; label: string; value: string | number; suffix?: string; valueClassName?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-3 transition-colors hover:border-foreground/20">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {icon}
        <span>{label}</span>
      </div>
      <div className="mt-1.5 flex items-baseline gap-0.5">
        <span className={`text-xl font-bold tracking-tight text-foreground ${valueClassName}`}>{value}</span>
        {suffix && <span className="text-xs text-muted-foreground">{suffix}</span>}
      </div>
    </div>
  )
}

function MetaCell({ icon, label, value, valueClassName = "" }: { icon: React.ReactNode; label: string; value: string | number; valueClassName?: string }) {
  return (
    <div className="flex flex-col gap-0.5 bg-card px-3 py-2.5">
      <span className="flex items-center gap-1 text-xs text-muted-foreground">
        {icon}
        {label}
      </span>
      <span className={`break-words text-sm font-medium text-foreground ${valueClassName}`}>{value}</span>
    </div>
  )
}
