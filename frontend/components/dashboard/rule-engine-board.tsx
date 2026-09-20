"use client";

import React, { useState, useEffect } from "react";
import {
  Save,
  AlertCircle,
  CheckCircle,
  Zap,
  Briefcase,
  MapPin,
  Plus,
  X,
  Trash2,
  Sparkles,
  Loader2,
} from "lucide-react";
import { MAIN_API_BASE } from "@/lib/platform-auth";

interface AIScoutRule {
  keyword: string;
  condition: "must" | "never";
  desc: string;
}



interface RuleEngineBoardProps {
  onSaveSuccess?: () => void;
}

export function RuleEngineBoard({ onSaveSuccess }: RuleEngineBoardProps) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{
    type: "success" | "error";
    msg: string;
  } | null>(null);

  const [minSalary, setMinSalary] = useState<number | "">(10);
  const [maxSalary, setMaxSalary] = useState<number | "">(25);
  const [maxExp, setMaxExp] = useState<number | "">(7);

  const [educationExclude, setEducationExclude] = useState<string[]>([]);
  const [educationRequire, setEducationRequire] = useState<string[]>([]);
  const [newEduReq, setNewEduReq] = useState("");
  const [cities, setCities] = useState<string[]>([]);
  const [safePhrases, setSafePhrases] = useState<string[]>([]);
  const [rawKeywordRules, setRawKeywordRules] = useState<any[]>([]);

  // 新增 Stage 2 LLM 配置字段
  const [aiScoutRules, setAiScoutRules] = useState<AIScoutRule[]>([]);
  const [predictingIdx, setPredictingIdx] = useState<number | null>(null);

  const [newEdu, setNewEdu] = useState("");
  const [newCity, setNewCity] = useState("");

  const fetchStrategy = async () => {
    try {
      const res = await fetch(`${MAIN_API_BASE}/strategy/active`);
      if (res.ok) {
        const data = await res.json();

        setMinSalary(
          !data.min_salary_k || data.min_salary_k === 0
            ? ""
            : data.min_salary_k,
        );
        setMaxSalary(
          !data.max_salary_k || data.max_salary_k >= 100
            ? ""
            : data.max_salary_k,
        );
        setMaxExp(
          !data.experience_years_max ||
            data.experience_years_max >= 20 ||
            data.experience_years_max === 0
            ? ""
            : data.experience_years_max,
        );

        setEducationExclude(
          Array.from(new Set(data.exclude_education || [])) as string[],
        );
        setEducationRequire(
          Array.from(new Set(data.require_education || [])) as string[],
        );
        setCities(Array.from(new Set(data.allowed_cities || [])) as string[]);
        setSafePhrases(
          Array.from(new Set(data.safe_phrases || [])) as string[],
        );

        // 完整保留已有的 keyword_rules 原始数据，防止保存时被抹平清空
        setRawKeywordRules(data.keyword_rules || []);

        // 新增状态同步
        setAiScoutRules(data.ai_scout_rules || []);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStrategy();
  }, []);

  const handleSaveAll = async () => {
    setSaving(true);
    try {
      const payloadMinSal = minSalary === "" ? 0 : minSalary;
      const payloadMaxSal = maxSalary === "" ? 999 : maxSalary;
      const payloadMaxExp = maxExp === "" ? 99 : maxExp;

      const res = await fetch(`${MAIN_API_BASE}/strategy/active`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          min_salary_k: payloadMinSal,
          max_salary_k: payloadMaxSal,
          experience_years_max: payloadMaxExp,
          exclude_education: educationExclude,
          require_education: educationRequire,
          allowed_cities: cities,
          safe_phrases: safePhrases,
          keyword_rules: rawKeywordRules,
          ai_scout_rules: aiScoutRules,
        }),
      });
      const result = await res.json();
      if (result.status === "success") {
        setToast({ type: "success", msg: "设置已更新" });
        if (onSaveSuccess) onSaveSuccess();
      } else {
        setToast({ type: "error", msg: "保存失败: " + result.message });
      }
    } catch (e) {
      setToast({ type: "error", msg: "网络请求异常" });
    } finally {
      setSaving(false);
      setTimeout(() => setToast(null), 3000);
    }
  };

  const handlePredictDesc = async (idx: number) => {
    const rule = aiScoutRules[idx];
    if (!rule.keyword.trim()) {
      setToast({ type: "error", msg: "请先输入关键字" });
      setTimeout(() => setToast(null), 3000);
      return;
    }

    setPredictingIdx(idx);
    try {
      const res = await fetch(`${MAIN_API_BASE}/strategy/predict_desc`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keyword: rule.keyword.trim() }),
      });
      const data = await res.json();
      if (res.ok && data.status === "success") {
        const newRules = [...aiScoutRules];
        newRules[idx].desc = data.data;
        setAiScoutRules(newRules);
      } else {
        throw new Error(data.message || "生成失败");
      }
    } catch (e: any) {
      setToast({ type: "error", msg: e.message || "预测失败" });
      setTimeout(() => setToast(null), 3000);
    } finally {
      setPredictingIdx(null);
    }
  };

  if (loading)
    return (
      <div className="flex h-[500px] w-full items-center justify-center text-zinc-400 text-sm tracking-wide bg-[#FBFBFD] rounded-[24px]">
        Loading Configuration...
      </div>
    );

  return (
    <div className="flex flex-col h-full w-full bg-[#FBFBFD] text-zinc-900 rounded-[24px] overflow-hidden relative font-sans">
      {/* Header */}
      <div className="flex-none px-8 pt-8 pb-5 flex items-end justify-between z-10 sticky top-0 bg-[#FBFBFD]/90 backdrop-blur-xl border-b border-zinc-200/50">
        <div>
          <h2 className="text-[24px] font-bold tracking-tight leading-tight">
            清洗规则
          </h2>
          <p className="text-[13px] text-zinc-500 mt-1 font-medium tracking-wide">
            全局拦截防线与模型打分策略
          </p>
        </div>
        <button
          onClick={handleSaveAll}
          disabled={saving}
          className="bg-black hover:bg-zinc-800 text-white rounded-full h-9 px-5 font-semibold text-[13px] shadow-sm transition-all duration-200 active:scale-95 flex items-center gap-2"
        >
          {saving ? "保存中..." : "保存"}
        </button>
      </div>

      {/* Content - Vertical Stack */}
      <div className="flex-1 overflow-y-auto px-8 py-6 space-y-8">
        {/* ===================== 硬规则清洗 ===================== */}
        <div className="space-y-6 relative">
          <h3 className="text-lg font-bold text-zinc-800 mb-1">硬规则清洗</h3>
          <p className="text-[13px] text-zinc-500 mb-4">
            物理阻断：数据将首先经过此层过滤，不符合直接丢弃
          </p>

          <div className="space-y-4">
            {/* Section 1: Salary & Experience */}
            <section className="bg-white rounded-[20px] shadow-[0_4px_20px_rgba(0,0,0,0.02)] p-6 border border-zinc-100/50">
              <div className="flex flex-col gap-4">
                <div className="flex items-center gap-3 bg-zinc-50/80 px-4 py-2.5 rounded-2xl border border-zinc-100/80 w-fit">
                  <div className="bg-white p-1.5 rounded-full shadow-sm mr-1">
                    <Briefcase className="w-4 h-4 text-zinc-700" />
                  </div>
                  <span className="text-[13px] font-medium text-zinc-500 whitespace-nowrap">
                    薪资限制
                  </span>

                  <div className="h-4 w-[1px] bg-zinc-200 mx-1"></div>

                  <input
                    type="number"
                    value={minSalary}
                    onChange={(e) =>
                      setMinSalary(
                        e.target.value === "" ? "" : Number(e.target.value),
                      )
                    }
                    placeholder="留空则不限"
                    className="w-20 bg-white text-center rounded-lg border border-zinc-100 py-1.5 focus:ring-2 focus:ring-black/5 outline-none font-semibold text-[13px] shadow-sm ml-2 placeholder:text-[12px] placeholder:font-normal placeholder:text-zinc-300"
                  />
                  <span className="text-[13px] font-medium text-zinc-500 whitespace-nowrap">
                    K &nbsp;—&nbsp;
                  </span>

                  <input
                    type="number"
                    value={maxSalary}
                    onChange={(e) =>
                      setMaxSalary(
                        e.target.value === "" ? "" : Number(e.target.value),
                      )
                    }
                    placeholder="留空则不限"
                    className="w-20 bg-white text-center rounded-lg border border-zinc-100 py-1.5 focus:ring-2 focus:ring-black/5 outline-none font-semibold text-[13px] shadow-sm placeholder:text-[12px] placeholder:font-normal placeholder:text-zinc-300"
                  />
                  <span className="text-[13px] font-medium text-zinc-500 whitespace-nowrap mr-2">
                    K
                  </span>
                </div>

                <div className="flex items-center gap-3 bg-zinc-50/80 px-4 py-2.5 rounded-2xl border border-zinc-100/80 w-fit">
                  <span className="text-[13px] font-medium text-zinc-500 whitespace-nowrap ml-2">
                    经验不超过
                  </span>
                  <input
                    type="number"
                    value={maxExp}
                    onChange={(e) =>
                      setMaxExp(
                        e.target.value === "" ? "" : Number(e.target.value),
                      )
                    }
                    placeholder="留空则不限"
                    className="w-24 bg-white text-center rounded-lg border border-zinc-100 py-1.5 focus:ring-2 focus:ring-black/5 outline-none font-semibold text-[13px] shadow-sm ml-1 placeholder:text-[12px] placeholder:font-normal placeholder:text-zinc-300"
                  />
                  <span className="text-[13px] font-medium text-zinc-500 ml-1">
                    年
                  </span>
                </div>
              </div>
            </section>

            {/* Section 2: Location & Education */}
            <section className="bg-white rounded-[20px] shadow-[0_4px_20px_rgba(0,0,0,0.02)] p-6 border border-zinc-100/50">
              <div className="flex items-center gap-2.5 mb-4 text-zinc-800">
                <div className="bg-zinc-100 p-1.5 rounded-full">
                  <MapPin className="w-4 h-4" />
                </div>
                <h3 className="font-semibold text-base tracking-tight">
                  地域与学历
                </h3>
              </div>
              <div className="flex flex-col sm:flex-row gap-5">
                <div className="flex-1 space-y-2">
                  <span className="text-[13px] font-medium text-zinc-500 block h-10">
                    目标城市
                  </span>
                  <input
                    type="text"
                    placeholder="输入城市后回车，如：杭州"
                    value={newCity}
                    onChange={(e) => setNewCity(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && newCity.trim()) {
                        setCities([...cities, newCity.trim()]);
                        setNewCity("");
                      }
                    }}
                    className="w-full text-[13px] px-3 py-2 rounded-xl bg-zinc-50 border border-zinc-100 outline-none focus:ring-2 focus:ring-black/5 transition-all placeholder:text-zinc-400 font-medium"
                  />
                  {cities.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {cities.map((c, idx) => (
                        <span
                          key={`${c}-${idx}`}
                          className="text-[12px] font-semibold bg-zinc-100 text-zinc-700 px-2.5 py-1 rounded-full flex items-center gap-1"
                        >
                          {c}
                          <button
                            onClick={() =>
                              setCities(cities.filter((x) => x !== c))
                            }
                            className="opacity-50 hover:opacity-100"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <div className="flex-1 space-y-2">
                  <span className="text-[13px] font-medium text-zinc-500 block h-10">
                    要求的学历 <br />
                    <span className="text-[11px] opacity-70">
                      (不填则默认不限)
                    </span>
                  </span>
                  <input
                    type="text"
                    value={newEduReq}
                    onChange={(e) => setNewEduReq(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && newEduReq.trim()) {
                        setEducationRequire([
                          ...educationRequire,
                          newEduReq.trim(),
                        ]);
                        setNewEduReq("");
                      }
                    }}
                    placeholder="输入学历后回车，如：本科"
                    className="w-full text-[13px] px-3 py-2 rounded-xl bg-zinc-50 border border-zinc-100 outline-none focus:ring-2 focus:ring-black/5 transition-all placeholder:text-zinc-400 font-medium"
                  />
                  {educationRequire.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {educationRequire.map((e, idx) => (
                        <span
                          key={`${e}-${idx}`}
                          className="text-[12px] font-semibold bg-blue-50 text-blue-600 px-2.5 py-1 rounded-full flex items-center gap-1"
                        >
                          {e}
                          <button
                            onClick={() =>
                              setEducationRequire(
                                educationRequire.filter((x) => x !== e),
                              )
                            }
                            className="opacity-50 hover:opacity-100"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <div className="flex-1 space-y-2">
                  <span className="text-[13px] font-medium text-zinc-500 block h-10">
                    一票否决的学历
                  </span>
                  <input
                    type="text"
                    placeholder="输入学历后回车，如：大专"
                    value={newEdu}
                    onChange={(e) => setNewEdu(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && newEdu.trim()) {
                        setEducationExclude([
                          ...educationExclude,
                          newEdu.trim(),
                        ]);
                        setNewEdu("");
                      }
                    }}
                    className="w-full text-[13px] px-3 py-2 rounded-xl bg-zinc-50 border border-zinc-100 outline-none focus:ring-2 focus:ring-black/5 transition-all placeholder:text-zinc-400 font-medium"
                  />
                  {educationExclude.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {educationExclude.map((e, idx) => (
                        <span
                          key={`${e}-${idx}`}
                          className="text-[12px] font-semibold bg-[#FFF0F0] text-[#E03131] px-2.5 py-1 rounded-full flex items-center gap-1"
                        >
                          {e}
                          <button
                            onClick={() =>
                              setEducationExclude(
                                educationExclude.filter((x) => x !== e),
                              )
                            }
                            className="opacity-50 hover:opacity-100"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </section>
          </div>
        </div>

        {/* ===================== Stage 2 大模型软清洗配置 ===================== */}
        <div className="space-y-6 relative mt-10">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-bold text-zinc-800 mb-1">大模型初筛配置 (Stage 2)</h3>
              <p className="text-[13px] text-zinc-500">
                AI 侦察兵：应对难以用正则穷举的红线词和复杂偏好。设定后，大模型将严格按照你的要求执行双重判定。
              </p>
            </div>
            <button
              onClick={() =>
                setAiScoutRules([
                  ...aiScoutRules,
                  { keyword: "", condition: "never", desc: "" },
                ])
              }
              className="flex items-center gap-1.5 px-4 py-2 bg-indigo-50 text-indigo-600 hover:bg-indigo-100 rounded-xl text-[13px] font-semibold transition-colors"
            >
              <Plus className="w-4 h-4" />
              添加规则
            </button>
          </div>

          <div className="space-y-4">
            {aiScoutRules.map((rule, idx) => (
              <div
                key={idx}
                className="bg-white rounded-[20px] shadow-[0_4px_20px_rgba(0,0,0,0.02)] p-5 border border-zinc-100/50 flex flex-col gap-4 group transition-all hover:border-indigo-100/80 hover:shadow-md"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 flex items-center gap-4">
                    <div className="flex flex-col gap-1.5 flex-1 max-w-[200px]">
                      <span className="text-[12px] font-semibold text-zinc-400 pl-1 uppercase tracking-wider">关键字 (Keyword)</span>
                      <input
                        type="text"
                        placeholder="例如: 双休"
                        value={rule.keyword}
                        onChange={(e) => {
                          const newRules = [...aiScoutRules];
                          newRules[idx].keyword = e.target.value;
                          setAiScoutRules(newRules);
                        }}
                        className="w-full text-[13px] px-3 py-2.5 rounded-xl bg-zinc-50 border border-zinc-100 outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500/50 transition-all font-medium placeholder:text-zinc-400"
                      />
                    </div>

                    <div className="flex flex-col gap-1.5">
                      <span className="text-[12px] font-semibold text-zinc-400 pl-1 uppercase tracking-wider">要求 (Condition)</span>
                      <div className="flex items-center p-1 bg-zinc-50 border border-zinc-100 rounded-xl">
                        <button
                          onClick={() => {
                            const newRules = [...aiScoutRules];
                            newRules[idx].condition = "must";
                            setAiScoutRules(newRules);
                          }}
                          className={`px-4 py-1.5 text-[13px] font-semibold rounded-lg transition-all ${rule.condition === "must"
                              ? "bg-emerald-100 text-emerald-700 shadow-sm"
                              : "text-zinc-500 hover:text-zinc-700"
                            }`}
                        >
                          必须包含
                        </button>
                        <button
                          onClick={() => {
                            const newRules = [...aiScoutRules];
                            newRules[idx].condition = "never";
                            setAiScoutRules(newRules);
                          }}
                          className={`px-4 py-1.5 text-[13px] font-semibold rounded-lg transition-all ${rule.condition === "never"
                              ? "bg-rose-100 text-rose-700 shadow-sm"
                              : "text-zinc-500 hover:text-zinc-700"
                            }`}
                        >
                          绝不包含
                        </button>
                      </div>
                    </div>
                  </div>

                  <button
                    onClick={() => {
                      const newRules = aiScoutRules.filter((_, i) => i !== idx);
                      setAiScoutRules(newRules);
                    }}
                    className="p-2 text-zinc-400 hover:bg-rose-50 hover:text-rose-500 rounded-xl transition-colors mt-6"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>

                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[12px] font-semibold text-zinc-400 pl-1 uppercase tracking-wider">AI 解释语 (Description for LLM)</span>
                    <button
                      onClick={() => handlePredictDesc(idx)}
                      disabled={predictingIdx === idx}
                      className="flex items-center gap-1.5 px-3 py-1 bg-amber-50 text-amber-600 hover:bg-amber-100 rounded-lg text-[12px] font-bold transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {predictingIdx === idx ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Sparkles className="w-3.5 h-3.5" />
                      )}
                      {predictingIdx === idx ? "生成中..." : "AI 辅助生成"}
                    </button>
                  </div>
                  <textarea
                    placeholder="向大模型解释这个关键字的具体判定标准，比如：1周休息2天为双休标准，大小周、单休、5天半工作制、每周工作6天、单双休、月休4+1天、月休4天、月休6天均不是双休..."
                    value={rule.desc}
                    onChange={(e) => {
                      const newRules = [...aiScoutRules];
                      newRules[idx].desc = e.target.value;
                      setAiScoutRules(newRules);
                    }}
                    className="w-full h-20 text-[13px] px-3 py-2.5 rounded-xl bg-zinc-50 border border-zinc-100 outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500/50 transition-all font-medium placeholder:text-zinc-400 resize-none leading-relaxed"
                  />
                </div>
              </div>
            ))}

            {aiScoutRules.length === 0 && (
              <div className="flex flex-col items-center justify-center py-12 px-4 border-2 border-dashed border-zinc-200 rounded-[20px] bg-zinc-50/50">
                <div className="bg-white p-3 rounded-2xl shadow-sm mb-3">
                  <Zap className="w-6 h-6 text-indigo-400" />
                </div>
                <h4 className="text-[14px] font-semibold text-zinc-700 mb-1">暂无 AI 侦察兵规则</h4>
                <p className="text-[13px] text-zinc-500 text-center max-w-sm mb-4">
                  添加结构化规则，让大模型帮你智能识别复杂的职位要求。
                </p>
                <button
                  onClick={() =>
                    setAiScoutRules([
                      { keyword: "", condition: "never", desc: "" },
                    ])
                  }
                  className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 text-white hover:bg-indigo-700 rounded-xl text-[13px] font-semibold transition-colors shadow-sm"
                >
                  <Plus className="w-4 h-4" />
                  添加第一条规则
                </button>
              </div>
            )}
          </div>
        </div>


      </div>

      {/* Toast Notification */}
      {toast && (
        <div className="absolute top-8 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 px-5 py-2.5 rounded-full shadow-[0_8px_30px_rgb(0,0,0,0.12)] text-[13px] font-semibold text-zinc-900 bg-white/90 backdrop-blur-md border border-zinc-100/50 animate-in fade-in slide-in-from-top-4">
          {toast.type === "success" ? (
            <CheckCircle className="h-4 w-4 text-emerald-500" />
          ) : (
            <AlertCircle className="h-4 w-4 text-rose-500" />
          )}
          {toast.msg}
        </div>
      )}
    </div>
  );
}
