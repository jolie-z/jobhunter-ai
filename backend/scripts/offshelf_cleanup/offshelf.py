#!/usr/bin/env python3
"""
已下架岗位清理 CLI（两段式：先 check 验活，再 move 归档，互不耦合）。

用法（用 backend/.venv/bin/python 运行）:
  offshelf.py fetch                          # 拉飞书岗位表全量快照 + 打印盘点矩阵
  offshelf.py check --sample 5               # 每平台抽 5 条试跑（近期+最旧混采），验证判定信号
  offshelf.py check                          # 全量验活（断点续查，已查过的自动跳过）
  offshelf.py report                         # 汇总 check 结果
  offshelf.py create-archive                 # 在同一本多维表格创建「已下架归档」表（字段镜像）
  offshelf.py move [--batch 50] [--limit N]  # 把确认死亡/已下架的记录搬进归档表（先建后删）

安全原则：
  - 「已投递」行无条件保留，永不参与检查与搬移
  - 判定三态：alive 活链 / dead 死链 / unknown 无法判定（异常、登录墙、验证码）——只搬 dead
  - check 结果逐条落盘断点续查；move 逐批先写入归档、成功后才删原表
"""
import argparse
import json
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import common as C


# ================================================================ fetch

def cmd_fetch(_args):
    print("拉取飞书岗位表全量记录 ...")
    raw = C.fetch_all_records()
    records = C.save_records_snapshot(raw)
    print(f"\n共 {len(records)} 条记录，盘点如下：\n")

    by_platform = Counter(r["platform"] or "(空)" for r in records)
    by_status = Counter(r["status"] or "(空)" for r in records)
    matrix = defaultdict(Counter)
    for r in records:
        matrix[r["platform"] or "(空)"][r["status"] or "(空)"] += 1

    print("按平台：")
    for p, n in by_platform.most_common():
        print(f"  {p}: {n}")
    print("\n按跟进状态：")
    for s, n in by_status.most_common():
        print(f"  {s}: {n}")

    print("\n平台 × 状态矩阵（本次清理范围 = 四平台）：")
    for p in C.SCOPE_PLATFORMS + ["小红书", "(空)"]:
        if p not in matrix:
            continue
        row = matrix[p]
        applied = row.get(C.STATUS_APPLIED, 0)
        offshelf = row.get(C.STATUS_OFFSHELF, 0)
        total = sum(row.values())
        to_check = total - applied - offshelf
        detail = "  ".join(f"{s}:{n}" for s, n in row.most_common())
        print(f"  [{p}] 总{total} | 已投递{applied}(保留) | 已标已下架{offshelf}(直接归档) | 需验活{to_check}")
        print(f"      {detail}")
    in_scope = sum(sum(matrix[p].values()) for p in C.SCOPE_PLATFORMS if p in matrix)
    applied = sum(matrix[p].get(C.STATUS_APPLIED, 0) for p in C.SCOPE_PLATFORMS if p in matrix)
    offshelf = sum(matrix[p].get(C.STATUS_OFFSHELF, 0) for p in C.SCOPE_PLATFORMS if p in matrix)
    print(f"\n四平台合计：{in_scope} 条 → 保留已投递 {applied}，直接归档已标已下架 {offshelf}，需浏览器验活 {in_scope - applied - offshelf}")


# ================================================================ check

def pick_check_targets(records: list, done: dict) -> dict:
    """按平台分组出需要验活的记录（排除已投递/已下架/已查过/无链接）。"""
    targets = defaultdict(list)
    for r in records:
        if r["platform"] not in C.SCOPE_PLATFORMS:
            continue
        if r["status"] in (C.STATUS_APPLIED, C.STATUS_OFFSHELF):
            continue
        if r["record_id"] in done:
            continue
        if not r["link"]:
            C.append_check_result({
                "record_id": r["record_id"], "platform": r["platform"],
                "verdict": "unknown", "reason": "无岗位链接", "checked_at": time.time(),
            })
            continue
        targets[r["platform"]].append(r)
    return targets


def make_checker(platform_value: str):
    """按平台返回 check(record) -> (verdict, reason)。延迟导入浏览器库。"""
    key = C.PLATFORM_KEY[platform_value]
    C.ensure_browser(key)

    if key == "51job":
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{C.resolve_port(key)}")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()

        # 显式死链信号（实测死链页文案："当前职位审核中或已下线"）
        DEAD_WORDS = ("已下线", "审核中", "职位不存在", "岗位不存在", "已过期", "已失效")

        def _wall_present() -> bool:
            try:
                if "滑动验证" in (page.title() or ""):
                    return True
                head = page.inner_text("body", timeout=2)[:150]
                return "访问验证" in head or "滑块" in head
            except Exception:
                return False

        def _wait_wall_cleared(max_wait: int = 1800) -> bool:
            """等待人工拖动滑块过验证，最长 max_wait 秒。"""
            t0 = time.time()
            while time.time() - t0 < max_wait:
                if not _wall_present():
                    return True
                time.sleep(10)
            return False

        def check(rec):
            try:
                page.goto(rec["link"], wait_until="domcontentloaded", timeout=30000)
                time.sleep(4)
                if _wall_present():
                    print("🚨 [51job] 触发滑动验证墙！请到 9227 端口的 Edge 窗口手动拖动滑块，脚本自动等待 ...", flush=True)
                    if not _wait_wall_cleared():
                        return "unknown", "验证墙超时未处理"
                    page.goto(rec["link"], wait_until="domcontentloaded", timeout=30000)
                    time.sleep(4)
                    print("✅ [51job] 验证已通过，继续验活", flush=True)
                for sel in (".close-btn",):
                    el = page.query_selector(sel)
                    if el:
                        try:
                            el.click()
                        except Exception:
                            pass
                final_url = page.url or ""
                if "login.51job.com" in final_url or "passport.51job.com" in final_url:
                    return "unknown", "登录墙"
                title = page.title() or ""
                h1 = page.query_selector(".cn h1") or page.query_selector("h1[title]")
                body_text = ""
                try:
                    body_text = page.inner_text("body", timeout=3000)[:600]
                except Exception:
                    pass
                # ① 显式死链信号优先
                if any(w in title or w in body_text for w in DEAD_WORDS):
                    return "dead", "页面显示已下线/审核中"
                # ② 存活信号
                if page.query_selector(".apply-btn-new") or h1:
                    return "alive", "有投递按钮/岗位标题"
                # ③ 都没有：可能是反爬空壳页，判 unknown 绝不误杀（下轮续查）
                return "unknown", "页面未加载完整"
            except Exception as exc:
                return "unknown", f"异常:{str(exc)[:60]}"
        return check, (4.0, 7.0)  # 51job 对频率敏感，放慢节奏

    # DrissionPage 系（boss / liepin / zhilian）
    from DrissionPage import ChromiumOptions, ChromiumPage
    co = ChromiumOptions()
    co.set_address(f"127.0.0.1:{C.resolve_port(key)}")
    co.set_browser_path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
    page = ChromiumPage(co)

    ALIVE_RULES = {
        "boss": [("text:立即沟通", 3), ("text:继续沟通", 2)],
        "liepin": [("css:a[data-selector=chat-chat]", 4), ("css:.btn-chat", 2),
                    ("text:聊一聊", 2), ("text:继续聊", 2)],
        "zhilian": [("text:立即投递", 2), ("text:申请职位", 2), ("text:投递简历", 2),
                     ("text:立即申请", 2), ("text:继续申请", 2)],
    }
    LOGIN_HOSTS = {
        "boss": ("passport.zhipin.com",),
        "liepin": ("login.liepin.com",),
        "zhilian": ("passport.zhaopin.com",),
    }
    # 真拦截页特征词（须配合"页面主文本极短"才成立——正常页脚注也可能出现这些词）
    BLOCK_WORDS = ("安全验证", "验证码", "滑动验证", "人机验证", "访问验证")
    # 显式死链文案（智联下架页实测特征："该职位已失效，看看其他机会吧"+"查看更多相似职位"）
    DEAD_WORDS_ZHILIAN = ("职位已失效", "看看其他机会", "更多相似职位",
                           "职位不存在", "岗位不存在", "已下线", "已过期", "停止招聘")

    def check(rec):
        try:
            page.get(rec["link"])
            time.sleep(random.uniform(2.5, 4))
            cur = page.url or ""
            for host in LOGIN_HOSTS[key]:
                if host in cur:
                    return "unknown", "登录墙"
            if key == "boss":
                if page.ele("css:#nc_1_n1z", timeout=0.5):
                    return "unknown", "验证码拦截"
            else:
                body = page.ele("tag:body", timeout=1)
                body_text = body.text if body else ""
                if len(body_text) < 200 and any(w in body_text for w in BLOCK_WORDS):
                    return "unknown", "验证码拦截"

            if key == "zhilian":
                # 智联岗位失效 → 重定向回首页/城市站，标题变成「xx招聘网_xx人才网…」
                title = page.title or ""
                if ("jobdetail" not in cur.lower() and "sou.zhaopin.com" not in cur.lower()
                        and ("招聘网" in title or cur.rstrip("/").endswith("zhaopin.com"))):
                    return "dead", "重定向回首页(岗位已消失)"
                if any(w in title or w in body_text for w in DEAD_WORDS_ZHILIAN):
                    return "dead", "页面显示职位已失效"

            for loc, tmo in ALIVE_RULES[key]:
                el = page.ele(loc, timeout=tmo)
                if el:
                    try:
                        if not el.states.is_displayed:
                            continue
                    except Exception:
                        pass
                    return "alive", f"存活信号:{loc}"

            if key == "zhilian":
                # 按钮可能懒加载：滚动触发后再查一次
                try:
                    page.scroll.down(800)
                    time.sleep(3)
                except Exception:
                    pass
                for loc, tmo in ALIVE_RULES[key]:
                    el = page.ele(loc, timeout=tmo)
                    if el:
                        try:
                            if not el.states.is_displayed:
                                continue
                        except Exception:
                            pass
                        return "alive", f"存活信号(懒加载后):{loc}"
                # JD 内容已渲染但无任何投递入口 → 与投递引擎同标准：不可投递即死链
                jd_box = page.ele("css:[class*=describtion]", timeout=2) or page.ele("text:职位描述", timeout=2)
                if jd_box:
                    return "dead", "内容在但无投递入口"
                return "unknown", "页面无信号"

            # 猎聘/BOSS 沿用「无存活信号=死链」（BOSS 为投递链路实战标准）
            return "dead", "页面无存活信号"
        except Exception as exc:
            return "unknown", f"异常:{str(exc)[:60]}"

    return check, (2.0, 3.5)


def run_check(targets: dict, parallel: bool = True):
    def worker(platform_value: str, recs: list):
        stats = Counter()
        check, pacing = make_checker(platform_value)
        total = len(recs)
        print(f"[{platform_value}] 开始验活 {total} 条", flush=True)
        consecutive_errors = 0
        for i, rec in enumerate(recs, 1):
            verdict, reason = check(rec)
            stats[verdict] += 1
            C.append_check_result({
                "record_id": rec["record_id"], "platform": platform_value,
                "verdict": verdict, "reason": reason,
                "job": f'{rec.get("company", "")} - {rec.get("job_name", "")}',
                "link": rec["link"], "checked_at": time.time(),
            })
            if verdict == "unknown" and ("登录墙" in reason or "验证码" in reason):
                consecutive_errors += 1
            else:
                consecutive_errors = 0
            if consecutive_errors >= 3:
                print(f"[{platform_value}] 连续登录墙/验证码，中止该平台（剩余 {total - i} 条下轮续查）", flush=True)
                break
            if i % 20 == 0 or i == total:
                print(f"[{platform_value}] {i}/{total} | 活{stats['alive']} 死{stats['dead']} 未知{stats['unknown']}", flush=True)
            time.sleep(random.uniform(*pacing))
        print(f"[{platform_value}] 完成：活{stats['alive']} 死{stats['dead']} 未知{stats['unknown']}", flush=True)
        return platform_value, stats

    if not parallel or len(targets) <= 1:
        for p, recs in targets.items():
            worker(p, recs)
        return
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futures = [pool.submit(worker, p, recs) for p, recs in targets.items()]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as exc:
                print(f"平台 worker 异常: {exc}", flush=True)


def cmd_check(args):
    records = C.load_records()
    done = C.load_check_results()
    targets = pick_check_targets(records, done)
    if args.platform:
        wanted = args.platform.split(",")
        targets = {p: v for p, v in targets.items() if p in wanted}
    total = sum(len(v) for v in targets.values())
    if total == 0:
        print("没有需要验活的记录（全部已查过或不在范围）。")
        return

    if args.sample:
        # 抽样：每平台取「最新3条 + 其余从最旧补齐」——近期链接应判活，验证信号正确性
        sampled = {}
        for p, recs in targets.items():
            recs_sorted = sorted(recs, key=lambda r: r.get("fields", {}).get("抓取时间") or "", reverse=True)
            picks = recs_sorted[:3]
            rest = sorted(recs_sorted[3:], key=lambda r: r.get("fields", {}).get("抓取时间") or "")
            picks += rest[: max(0, args.sample - 3)]
            sampled[p] = picks
        targets = sampled
        total = sum(len(v) for v in targets.values())
        print(f"抽样模式：每平台最多 {args.sample} 条（近期3条+最旧补足），共 {total} 条\n")

    print(f"待验活：{ {p: len(v) for p, v in targets.items()} }\n")
    run_check(targets, parallel=not args.serial)
    print("\n抽样/验活结束，运行 offshelf.py report 查看汇总。")


def cmd_report(_args):
    results = C.load_check_results()
    if not results:
        print("还没有 check 结果。")
        return
    by = defaultdict(Counter)
    unknown_reasons = Counter()
    for item in results.values():
        by[item["platform"]][item["verdict"]] += 1
        if item["verdict"] == "unknown":
            unknown_reasons[item["reason"].split(":")[0]] += 1
    print("验活结果汇总：")
    for p in C.SCOPE_PLATFORMS:
        if p in by:
            c = by[p]
            print(f"  {p}: 活 {c['alive']} | 死 {c['dead']} | 未知 {c['unknown']}")
    if unknown_reasons:
        print("\n未知原因分布：")
        for reason, n in unknown_reasons.most_common():
            print(f"  {reason}: {n}")
    dead = [r for r in results.values() if r["verdict"] == "dead"]
    print(f"\n死链样例（前 5 条，共 {len(dead)} 条）：")
    for r in dead[:5]:
        print(f"  [{r['platform']}] {r.get('job', '')} | {r['reason']} | {r['link']}")


# ================================================================ move

READONLY_FIELD_NAMES_CACHE = {}


def readonly_field_names() -> set:
    if "names" not in READONLY_FIELD_NAMES_CACHE:
        names = set()
        for f in C.list_fields(C.JOBS_TABLE_ID):
            if f.get("type") in C.READONLY_FIELD_TYPES:
                names.add(f["field_name"])
        READONLY_FIELD_NAMES_CACHE["names"] = names
    return names


def move_candidates(records: list, results: dict) -> list:
    """dead 判定的 + 原本就标「已下架」的（排除已投递）。"""
    cands = []
    for r in records:
        if r["platform"] not in C.SCOPE_PLATFORMS:
            continue
        if r["status"] == C.STATUS_APPLIED:
            continue
        res = results.get(r["record_id"])
        if r["status"] == C.STATUS_OFFSHELF:
            cands.append((r, "原表已标已下架"))
        elif res and res["verdict"] == "dead":
            cands.append((r, f"验活判定:{res.get('reason', '')}"))
    return cands


def cmd_create_archive(_args):
    table_id = C.create_archive_table()
    C.ARCHIVE_META.write_text(json.dumps({
        "table_id": table_id, "created_at": datetime.now().isoformat(),
    }, ensure_ascii=False), encoding="utf-8")
    print(f"归档表元数据已写入 {C.ARCHIVE_META}")


def cmd_move(args):
    if not C.ARCHIVE_META.exists():
        raise SystemExit("归档表不存在，请先运行: offshelf.py create-archive")
    archive_table = json.loads(C.ARCHIVE_META.read_text(encoding="utf-8"))["table_id"]

    records = C.load_records()
    results = C.load_check_results()
    cands = move_candidates(records, results)

    moved_log = set()
    if C.MOVE_LOG.exists():
        for line in C.MOVE_LOG.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entry = json.loads(line)
                if entry.get("ok"):
                    moved_log.update(entry["src_ids"])
    cands = [(r, reason) for r, reason in cands if r["record_id"] not in moved_log]
    print(f"待归档 {len(cands)} 条（已剔除已搬移），归档表 {archive_table}")
    if args.limit:
        cands = cands[: args.limit]
    if not cands:
        print("没有需要搬移的记录。")
        return

    ro_names = readonly_field_names()  # 仅用于日志提示，白名单已天然排除
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    ok_total = 0
    for i in range(0, len(cands), args.batch):
        chunk = cands[i: i + args.batch]
        src_ids = [r["record_id"] for r, _ in chunk]
        fields_list = []
        for r, reason in chunk:
            fields = {k: v for k, v in r["fields"].items()
                      if k in C.ARCHIVE_FIELD_WHITELIST and v is not None}
            fields["归档时间"] = now_str
            fields["归档原因"] = reason
            fields_list.append(fields)
        try:
            new_ids = C.batch_create_records(archive_table, fields_list)
            assert len(new_ids) == len(chunk), f"归档写入数量不符: {len(new_ids)}/{len(chunk)}"
            C.batch_delete_records(C.JOBS_TABLE_ID, src_ids)
            ok_total += len(chunk)
            with C.MOVE_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ok": True, "batch_size": len(chunk), "src_ids": src_ids,
                    "archive_ids": new_ids, "at": datetime.now().isoformat(),
                }, ensure_ascii=False) + "\n")
            print(f"  批次 {i // args.batch + 1}: {len(chunk)} 条 归档+删除成功（累计 {ok_total}）", flush=True)
            time.sleep(0.5)
        except Exception as exc:
            print(f"  批次 {i // args.batch + 1} 失败，停止（该批未删原表，可重跑续搬）: {exc}", flush=True)
            break
    print(f"\n搬移完成：成功 {ok_total}/{len(cands)}")
    if ok_total > 0:
        try:
            import requests as _req
            r = _req.post("http://127.0.0.1:8000/api/jobs/refresh-cache", timeout=10)
            print(f"后端岗位缓存清理: HTTP {r.status_code}")
        except Exception as exc:
            print(f"提示：后端缓存清理失败（不影响归档结果，前端最多 1 小时后自动刷新）: {exc}")


# ================================================================ main

# common 里补一个端口查询（避免脚本内直接 import app 包）
def _resolve_port(platform_key: str) -> int:
    sys.path.insert(0, str(C.BACKEND_ROOT))
    from app.session.registry import get_platform_port
    return get_platform_port(platform_key)


C.resolve_port = _resolve_port


def main():
    parser = argparse.ArgumentParser(description="已下架岗位清理")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("fetch", help="拉全量快照并盘点")
    p_check = sub.add_parser("check", help="浏览器验活")
    p_check.add_argument("--sample", type=int, default=0, help="每平台抽样条数（试跑）")
    p_check.add_argument("--serial", action="store_true", help="平台串行执行（默认并行）")
    p_check.add_argument("--platform", default="", help="只跑指定平台（逗号分隔，如 猎聘,51job）")
    sub.add_parser("report", help="汇总验活结果")
    sub.add_parser("create-archive", help="创建归档表")
    p_move = sub.add_parser("move", help="批量归档并删除原表记录")
    p_move.add_argument("--batch", type=int, default=50)
    p_move.add_argument("--limit", type=int, default=0)

    args = parser.parse_args()
    {"fetch": cmd_fetch, "check": cmd_check, "report": cmd_report,
     "create-archive": cmd_create_archive, "move": cmd_move}[args.cmd](args)


if __name__ == "__main__":
    main()
