#!/usr/bin/env bash
# agy_review.sh — 独立审查单轮执行引擎（三道岗哨统一入口；scripts/review.sh 软链到此）
#
# 用法:
#   scripts/review.sh --mode <double-check|plan-review|code-review> --round <N> \
#                     --title "<一句话标题>" --material <材料文件> [--engine agy|zcode] [--model <模型ID>]
# 退出码: 0 = VERDICT: PASS · 1 = VERDICT: QUESTIONS · 2 = 引擎调用失败 / 回复缺少 verdict 行
#
# 职责边界：只做「拼 prompt → 调 Reviewer → 解析 verdict → 落盘 + 原文回显」这一轮；
# 多轮循环、逐条回应、3 轮熔断由 .agents/skills/agy-* 技能驾驭。
#
# 2026-09-16 重建：53f1651 误把本文件写成 exec 自身的 wrapper（死循环），原引擎内容
# 从未入库；此版按 docs/reports/agy-review/ 已落盘日志中的完整 prompt 与记录格式原样复原。
set -uo pipefail

MODE=""
ROUND=""
TITLE=""
MATERIAL=""
ENGINE="${ENGINE:-zcode}"
MODEL=""
PRINT_TIMEOUT="${REVIEW_PRINT_TIMEOUT:-10m}"
MAX_PROMPT_BYTES=900000   # macOS ARG_MAX 1MB，prompt 走命令行参数，超限提示拆分材料

usage() {
  sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --mode) MODE="${2:-}"; shift 2 ;;
    --round) ROUND="${2:-}"; shift 2 ;;
    --title) TITLE="${2:-}"; shift 2 ;;
    --material) MATERIAL="${2:-}"; shift 2 ;;
    --engine) ENGINE="${2:-}"; shift 2 ;;
    --model) MODEL="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$MODE" in
  double-check|plan-review|code-review) ;;
  *) echo "--mode 必须是 double-check | plan-review | code-review（当前: '${MODE}'）" >&2; exit 2 ;;
esac
if ! [[ "$ROUND" =~ ^[0-9]+$ ]]; then
  echo "--round 必须是正整数（当前: '${ROUND}'）" >&2; exit 2
fi
if [ -z "$TITLE" ]; then
  echo "--title 不能为空" >&2; exit 2
fi
if [ -z "$MATERIAL" ] || [ ! -f "$MATERIAL" ]; then
  echo "--material 文件不存在: '${MATERIAL}'" >&2; exit 2
fi

case "$ENGINE" in
  agy)
    MODEL="${MODEL:-gemini-3.8-flash-high}"
    AGY_BIN="${AGY_BIN:-$(command -v agy 2>/dev/null || echo "$HOME/.local/bin/agy")}"
    if [ ! -x "$AGY_BIN" ]; then
      echo "找不到 agy CLI（尝试过 PATH 与 $HOME/.local/bin/agy），可用 AGY_BIN=/path/to/agy 指定" >&2; exit 2
    fi
    ;;
  zcode)
    MODEL="${MODEL:-bigmodel/glm-5.3-flash}"
    ZCODE_BIN="${ZCODE_BIN:-$(command -v zcode 2>/dev/null || echo "$HOME/.local/bin/zcode")}"
    if [ ! -x "$ZCODE_BIN" ]; then
      echo "找不到 zcode CLI（尝试过 PATH 与 $HOME/.local/bin/zcode），可用 ZCODE_BIN=/path/to/zcode 指定" >&2; exit 2
    fi
    ;;
  *) echo "--engine 必须是 agy | zcode（当前: '${ENGINE}'）" >&2; exit 2 ;;
esac

case "$MODEL" in
  gemini-3.8-flash-high) MODEL_LABEL="Gemini 3.8 Flash (High)" ;;
  bigmodel/glm-5.3-flash|glm-5.3-flash) MODEL_LABEL="GLM 5.3 Flash" ;;
  bigmodel/glm-5.3|glm-5.3) MODEL_LABEL="GLM 5.3" ;;
  *) MODEL_LABEL="$MODEL" ;;
esac

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$REPO_ROOT/docs/reports/agy-review"
mkdir -p "$LOG_DIR"
TS="$(date +%Y-%m-%d_%H%M%S)"
LOG_FILE="$LOG_DIR/${TS}_${MODE}_round${ROUND}.md"

# ---------- prompt 骨架（与历史落盘日志逐字一致） ----------
COMMON_RULES='你是一名严苛但公正的资深审查员。另一位 AI 工程师完成了一项工作，现在由你做独立的 double check。你的价值在于找出真实存在的问题，而不是走过场，也不是为了显得严格而编造问题。

## 审查规则
1. 只依据下方「材料」进行分析。不要使用任何工具，不要读写文件，不要执行命令，不要假设材料之外的代码或事实。
2. 每一条质疑都必须引用材料中的具体位置（文件名/行号/原文片段）作为依据；没有依据的猜测不要写。
3. 严格区分两类意见：
   - 硬性问题（P0/P1）：会导致功能错误、回归、数据或安全风险、结论不成立。
   - 判断性建议（P2）：风格、可读性、可选优化、锦上添花。
   只有「硬性问题」才构成质疑并影响 verdict；判断性建议单独列出、不影响 verdict。
4. 若材料包含「## 历史轮次」，说明这不是第一轮：先逐条核对上一轮你提出的每个问题是否已被妥善解决或有理有据地反驳，明确写出「已解决 / 反驳成立 / 仍未解决」，已解决的不要重复提出，也不要为了凑数新增无依据的问题。
5. 用中文回答，先给结论摘要，再列问题。
6. 你的回复最后一行必须是且只能是下面两种之一（单独成行，不加粗、不加其他文字）：
VERDICT: PASS
VERDICT: QUESTIONS
存在任何未解决的硬性问题时输出 QUESTIONS，否则输出 PASS。'

case "$MODE" in
  double-check)
    MODE_FOCUS='## 本轮审查重点（结论 double check）
审查对象是一份排查结论 / 质检报告 / 审查意见（含证据链与验证方式）。请重点检查：
(1) 证据是否足以支撑结论：每个关键论断是否都有对应证据，证据是否被正确解读；
(2) 是否存在被忽略的替代解释或其他根因；
(3) 推理链是否有逻辑跳跃、循环论证或过度外推；
(4) 结论是否可验证：给出的验证方式是否真的能证伪该结论；
(5) 建议的修复 / 动作是否与结论匹配，副作用是否评估。
输出格式：每条一行 `[P0|P1|P2] 位置 — 质疑 — 建议如何验证或修正`。' ;;
  plan-review)
    MODE_FOCUS='## 本轮审查重点（实施方案 plan review）
审查对象是一份即将实施的方案（implementation_plan.md）。请重点检查：
(1) 数据锚定与字段合规：严禁盲目凭空造字段！是否核对了飞书多维表格（Bitable）或本地数据库中的既有表结构？涉及读写字段是否均有明确定义？
(2) 模块化与防堆砌：涉及修改的文件在变更后是否会接近或超过 500 行？如果过长，方案是否规划了拆分独立的 hooks、utils 或单独的 API 路由？
(3) 依赖与边界风险：改动是否引起循环依赖？是否破坏现有的公共接口？
(4) 异常处理与可回滚性：是否包含失败兜底与数据回滚机制？
(5) 验证闭环：方案中的验证计划是否具体可执行？
输出格式：每条一行 `[P0|P1|P2] 模块/设计点 — 质疑 — 改进建议`。' ;;
  code-review)
    MODE_FOCUS='## 本轮审查重点（code review）
审查对象是一次代码变更（施工说明 + diff）。请沿两条轴线分别审查、不要合并：
- Standards 轴：变更是否符合材料中给出的仓库规范；以及是否出现以下代码坏味道（均属判断性建议，需引用 hunk）：Mysterious Name、Duplicated Code、Feature Envy、Data Clumps、Primitive Obsession、Repeated Switches、Shotgun Surgery、Divergent Change、Speculative Generality、Message Chains、Middle Man、Refused Bequest。
- Spec 轴：(a) 施工说明要求了但缺失或只做了一半的；(b) 做了但没被要求的行为（scope creep）；(c) 看起来实现了但实现有误的。
此外必须检查：正确性与边界条件、回归风险、错误处理、安全（注入 / 泄露 / 权限）、shell 或脚本的引号与转义。
输出格式：每条一行 `[P0|P1|P2] 文件:行 — 问题 — 建议`。' ;;
esac

MATERIAL_BODY="$(cat "$MATERIAL")"
PROMPT="${COMMON_RULES}

${MODE_FOCUS}

## 材料（第 ${ROUND} 轮） · ${TITLE}

${MATERIAL_BODY}"

PROMPT_BYTES=$(printf '%s' "$PROMPT" | wc -c | tr -d ' ')
if [ "$PROMPT_BYTES" -gt "$MAX_PROMPT_BYTES" ]; then
  echo "材料过大（prompt ${PROMPT_BYTES} 字节 > ${MAX_PROMPT_BYTES}），请按模块/commit 拆成多份材料分别送审" >&2
  exit 2
fi

# ---------- 调用 Reviewer ----------
RESP_FILE="$(mktemp -t agy_review_resp)"
ERR_FILE="$(mktemp -t agy_review_err)"
trap 'rm -f "$RESP_FILE" "$ERR_FILE"' EXIT

START_TS=$(date +%s)
if [ "$ENGINE" = "zcode" ]; then
  "$ZCODE_BIN" -p "$PROMPT" >"$RESP_FILE" 2>"$ERR_FILE"
  RC=$?
else
  "$AGY_BIN" --model "$MODEL" --disable-slash-commands --print-timeout "$PRINT_TIMEOUT" --print="$PROMPT" \
    >"$RESP_FILE" 2>"$ERR_FILE"
  RC=$?
fi
ELAPSED=$(( $(date +%s) - START_TS ))

RESPONSE="$(cat "$RESP_FILE")"
STDERR_TEXT="$(cat "$ERR_FILE")"

# 遇到 503 容量限制时，自动降级切换至备用模型重试一次（针对 agy 引擎）
if [ "$ENGINE" = "agy" ] && [ "$RC" -ne 0 ] && echo "$STDERR_TEXT $RESPONSE" | grep -qiE "503|capacity" && [ "$MODEL" = "gemini-3.8-flash-high" ]; then
  echo "[review.sh] gemini-3.8-flash-high 遇到 503 容量限制，自动降级至 gemini-3.7-flash-high 重试..." >&2
  MODEL="gemini-3.7-flash-high"
  MODEL_LABEL="Gemini 3.7 Flash (High) [Fallback]"
  "$AGY_BIN" --model "$MODEL" --disable-slash-commands --print-timeout "$PRINT_TIMEOUT" --print="$PROMPT" \
    >"$RESP_FILE" 2>"$ERR_FILE"
  RC=$?
  ELAPSED=$(( $(date +%s) - START_TS ))
  RESPONSE="$(cat "$RESP_FILE")"
  STDERR_TEXT="$(cat "$ERR_FILE")"
fi

# verdict = 最后一个非空行；容忍首尾空白与误加的 markdown 加粗
LAST_LINE="$(printf '%s\n' "$RESPONSE" | sed -e 's/[[:space:]]*$//' | grep -v '^$' | tail -n 1 | sed -e 's/^[*[:space:]]*//' -e 's/[*[:space:]]*$//')"
case "$LAST_LINE" in
  "VERDICT: PASS") VERDICT="PASS" ;;
  "VERDICT: QUESTIONS") VERDICT="QUESTIONS" ;;
  *) VERDICT="NONE" ;;
esac
if [ "$RC" -ne 0 ]; then
  VERDICT="ERROR"
fi

# ---------- 落盘（白盒记录，格式与历史日志一致） ----------
{
  echo "# Review 记录 · ${MODE} · round ${ROUND}"
  echo
  echo "- 时间: ${TS}"
  echo "- 引擎: ${ENGINE}"
  echo "- 模型: ${MODEL_LABEL}"
  echo "- 标题: ${TITLE}"
  echo "- 材料文件: ${MATERIAL}"
  echo "- 执行退出码: ${RC}"
  echo "- 耗时: ${ELAPSED}s"
  echo "- **Verdict: ${VERDICT}**"
  echo
  echo "## 发送给审阅员的完整 prompt"
  echo
  echo '`````text'
  printf '%s\n' "$PROMPT"
  echo '`````'
  echo
  echo "## 审阅员原文回复"
  echo
  echo '`````text'
  printf '%s\n' "$RESPONSE"
  echo '`````'
  if [ -n "$STDERR_TEXT" ]; then
    echo
    echo "## 引擎 stderr"
    echo
    echo '`````text'
    printf '%s\n' "$STDERR_TEXT"
    echo '`````'
  fi
} >"$LOG_FILE"

# ---------- 原文回显 + 摘要行 ----------
printf '%s\n' "$RESPONSE"
if [ -n "$STDERR_TEXT" ]; then
  echo
  echo "[engine stderr]"
  printf '%s\n' "$STDERR_TEXT"
fi
echo
echo "---"
echo "VERDICT=${VERDICT}  AGY_RC=${RC}  ELAPSED=${ELAPSED}s"
echo "LOG=${LOG_FILE}"

case "$VERDICT" in
  PASS) exit 0 ;;
  QUESTIONS) exit 1 ;;
  *) exit 2 ;;
esac
