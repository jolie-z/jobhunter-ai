#!/usr/bin/env bash
# ============================================
# 夜间自主任务总控（2026-08-31）
# 零人工配合：喂批清洗管道 + 健康监督 + 自动止损 + 晨报
# ============================================
set -u
cd <repo-root>
LOG=/tmp/overnight_master.log
MORNING=/tmp/晨报_2026-08-31.md
PY=backend/.venv/bin/python
DB=backend/data/job_hunter.db
API=http://127.0.0.1:8000

echo "# 夜间执行晨报（$(date '+%F %T') 生成）" > "$MORNING"
exec >> "$LOG" 2>&1
echo "===== 夜间总控启动 $(date) ====="

# ---------- 前置体检：后端必须活着，否则直接收工 ----------
if ! curl -s --max-time 10 "$API/docs" -o /dev/null; then
  echo "❌ 后端无响应，夜间任务中止（不擅自启动生产服务）" >> "$MORNING"
  exit 1
fi

# ---------- 阶段一：668 条积压分批喂入清洗管道 ----------
BACKLOG=$($PY -c "
import sqlite3
c = sqlite3.connect('$DB')
print(c.execute(\"SELECT COUNT(*) FROM raw_jobs WHERE process_status='已存入数据'\").fetchone()[0])
")
echo "启动时积压: $BACKLOG" >> "$MORNING"

ROUNDS=0
while true; do
  NOW=$($PY -c "
import sqlite3
c = sqlite3.connect('$DB')
print(c.execute(\"SELECT COUNT(*) FROM raw_jobs WHERE process_status='已存入数据'\").fetchone()[0])
")
  if [ "$NOW" -le 30 ]; then echo "积压已排空（剩 $NOW）" >> "$MORNING"; break; fi
  if [ "$ROUNDS" -ge 12 ]; then echo "达 12 轮上限，停止（防 LLM 费用失控）" >> "$MORNING"; break; fi

  RES=$(curl -s --max-time 30 -X POST "$API/api/v1/processor/run-global" -H "Content-Type: application/json" -d '{"limit": 60}')
  echo "[轮 $((ROUNDS+1))] 触发清洗: $RES (当时积压 $NOW) $(date '+%T')" >> "$MORNING"

  # 监控本轮 20 分钟：等待状态数下降，同时验证后端健康
  STALL=0
  for i in $(seq 1 20); do
    sleep 60
    if ! curl -s --max-time 10 "$API/docs" -o /dev/null; then
      echo "❌ 后端失联，立即止损收工" >> "$MORNING"; break 2
    fi
    CHECK=$($PY -c "
import sqlite3
c = sqlite3.connect('$DB')
print(c.execute(\"SELECT COUNT(*) FROM raw_jobs WHERE process_status='已存入数据'\").fetchone()[0])
")
    if [ "$CHECK" -lt "$NOW" ]; then break; fi   # 本轮有消化，进入下一轮
    if [ $((i % 10)) -eq 0 ]; then echo "  [警告] ${i}分钟无进展 (积压 $CHECK)" >> "$MORNING"; fi
  done
  ROUNDS=$((ROUNDS+1))
done

# ---------- 阶段二：pytest 全量回归 ----------
echo "## pytest 回归" >> "$MORNING"
cd backend
PYTEST=$($PY -m pytest tests_pipeline/ -q 2>&1 | tail -2)
echo "\`\`\`
$PYTEST
\`\`\`" >> "$MORNING"
cd ..

# ---------- 阶段三：终态统计 ----------
$PY - "$MORNING" <<'EOF'
import sqlite3, sys
c = sqlite3.connect('backend/data/job_hunter.db')
total = c.execute("SELECT COUNT(*) FROM raw_jobs").fetchone()[0]
pending = c.execute("SELECT COUNT(*) FROM raw_jobs WHERE process_status='已存入数据'").fetchone()[0]
synced = c.execute("SELECT COUNT(*) FROM raw_jobs WHERE process_status='已同步'").fetchone()[0]
await_push = c.execute("SELECT COUNT(*) FROM raw_jobs WHERE process_status='待推送至飞书'").fetchone()[0]
with open(sys.argv[1], 'a') as f:
    f.write(f"## 终态统计\n- 全表: {total} | 积压剩余: {pending} | 已同步: {synced} | 待推送: {await_push}\n")
EOF

echo "===== 夜间总控结束 $(date) =====" >> "$LOG"
echo "夜间任务完成，晨报见 $MORNING" >> "$MORNING"
