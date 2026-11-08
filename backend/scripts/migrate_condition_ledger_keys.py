#!/usr/bin/env python3
"""
一次性迁移：把「平台映射 key」下的旧台账行合并回「标准条件 key」。

背景
----
2026-10-30 之前，各平台 controller 用 map_salary()/adapt_keyword() 之后的
平台原生关键词/薪资写 scrape_sessions，而编排器/前端用标准条件读取。
典型表现：智联 15-20K 被映射成 15K-25K，真实进度写在 15K-25K 行，
UI 却一直显示“待抓”。

修复后新写入统一走标准 key；本脚本负责把存量映射行合并回标准行：

  标准行 scraped_count += 映射行 scraped_count
  标准行 predicted_total = max(两行)
  标准行 last_page 保留标准行原值（没有标准行则置 0，下次从第 1 页重扫）
  标准行 exhausted_at / no_new_rounds 取两行中更“已抓尽”的一方
  删除映射行

用法
----
  cd backend
  pm2 stop jobhunter-backend                                  # 必须先停后端
  python scripts/migrate_condition_ledger_keys.py --dry-run    # 先看计划（不写库）
  python scripts/migrate_condition_ledger_keys.py --force      # 确认已停服后执行

安全：
- 实际迁移会先拿 SQLite 写锁（BEGIN IMMEDIATE），整个合并在一个事务里完成，
  避免后端仍在运行时读-改-写窗口被并发累加覆盖；
- 未加 --force 时脚本只提示、不写库；
- 只处理当前 pipeline_scrape_config 里的条件；已移除/改名的条件行保持原样。

脚本幂等：映射行删除后，再跑不会重复累加。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.db_paths import job_hunter_db_path  # noqa: E402
from app.session.salary_mapper import adapt_keyword, map_salary  # noqa: E402

PLATFORMS = ["boss", "liepin", "51job", "zhilian", "xiaohongshu"]
DEFAULT_DB = job_hunter_db_path(str(BACKEND_DIR / "data" / "job_hunter.db"))


def _load_config(conn: sqlite3.Connection) -> dict:
    try:
        row = conn.execute(
            "SELECT keywords, default_city, default_salary FROM pipeline_scrape_config WHERE id=1"
        ).fetchone()
    except sqlite3.OperationalError:
        return {"keywords": [], "default_city": "", "default_salary": ""}
    if not row:
        return {"keywords": [], "default_city": "", "default_salary": ""}
    try:
        keywords = json.loads(row[0] or "[]")
    except (TypeError, ValueError):
        keywords = []
    return {
        "keywords": keywords if isinstance(keywords, list) else [],
        "default_city": row[1] or "",
        "default_salary": row[2] or "",
    }


def _columns(conn: sqlite3.Connection) -> set[str]:
    try:
        return {r[1] for r in conn.execute("PRAGMA table_info(scrape_sessions)").fetchall()}
    except sqlite3.OperationalError:
        return set()


def _row(conn, cols: set[str], keyword, city, salary, platform):
    scraped = "scraped_count" if "scraped_count" in cols else "0"
    predicted = "predicted_total" if "predicted_total" in cols else "0"
    page = "last_page" if "last_page" in cols else "1"
    exhausted = "exhausted_at" if "exhausted_at" in cols else "''"
    no_new = "no_new_rounds" if "no_new_rounds" in cols else "0"
    return conn.execute(
        f"SELECT {scraped}, {predicted}, {page}, {exhausted}, {no_new} "
        "FROM scrape_sessions WHERE keyword=? AND city=? AND salary=? AND platform=?",
        (keyword, city, salary, platform),
    ).fetchone()


def _merge(conn, cols: set[str], standard, native, dry_run: bool) -> bool:
    skw, scity, ssalary, platform = standard
    nkw, ncity, nsalary, _ = native
    std = _row(conn, cols, skw, scity, ssalary, platform)
    nat = _row(conn, cols, nkw, ncity, nsalary, platform)
    if not nat:
        return False
    nat_scraped, nat_predicted, nat_page, nat_exhausted, nat_no_new = nat
    if std:
        std_scraped, std_predicted, std_page, std_exhausted, std_no_new = std
        merged = (
            int(std_scraped or 0) + int(nat_scraped or 0),
            max(int(std_predicted or 0), int(nat_predicted or 0)),
            int(std_page or 0),
            (std_exhausted or "") or (nat_exhausted or ""),
            max(int(std_no_new or 0), int(nat_no_new or 0)),
        )
        action = "merge"
    else:
        merged = (
            int(nat_scraped or 0),
            int(nat_predicted or 0),
            0,  # 映射行的 last_page 不可信，强制从第 1 页重扫
            nat_exhausted or "",
            int(nat_no_new or 0),
        )
        action = "create"

    print(
        f"[{action}] {platform}: {nkw!r}/{ncity!r}/{nsalary!r} "
        f"({nat_scraped}/{nat_predicted}, page={nat_page}) "
        f"-> {skw!r}/{scity!r}/{ssalary!r} "
        f"=> {merged[0]}/{merged[1]}, page={merged[2]}"
    )
    if dry_run:
        return True

    conn.execute(
        """INSERT INTO scrape_sessions
           (keyword, city, salary, platform, last_page, last_run, predicted_total,
            scraped_count, exhausted_at, no_new_rounds)
           VALUES (?, ?, ?, ?, ?, COALESCE((SELECT last_run FROM scrape_sessions
                    WHERE keyword=? AND city=? AND salary=? AND platform=?), ''),
                   ?, ?, ?, ?)
           ON CONFLICT(keyword, city, salary, platform) DO UPDATE SET
             scraped_count = excluded.scraped_count,
             predicted_total = excluded.predicted_total,
             last_page = excluded.last_page,
             exhausted_at = excluded.exhausted_at,
             no_new_rounds = excluded.no_new_rounds""",
        (
            skw, scity, ssalary, platform, merged[2],
            skw, scity, ssalary, platform,
            merged[1], merged[0], merged[3], merged[4],
        ),
    )
    conn.execute(
        "DELETE FROM scrape_sessions WHERE keyword=? AND city=? AND salary=? AND platform=?",
        (nkw, ncity, nsalary, platform),
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="合并平台映射 key 下的旧条件台账")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"SQLite 路径（默认 {DEFAULT_DB}）")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写库（不产生逻辑写入）")
    parser.add_argument("--force", action="store_true", help="确认后端已停止，允许实际写库")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"❌ 数据库不存在: {db_path}")
        return 2

    if not args.dry_run and not args.force:
        print("⚠️ 实际迁移会修改生产库；请先停止后端（pm2 stop jobhunter-backend）。")
        print("   确认已停服后加 --force 重新执行；或先用 --dry-run 查看计划。")
        return 3

    if args.dry_run:
        # WAL 库停服后可能没有 -shm，sqlite3 的 mode=ro 会报 "unable to open database file"。
        # dry-run 只做读操作：普通连接 + query_only + 末尾 rollback，不会产生逻辑写入
        # （最多生成空的 -wal/-shm）。
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA query_only=1")
    else:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS scrape_sessions ("
                "keyword TEXT NOT NULL, city TEXT NOT NULL DEFAULT '', "
                "salary TEXT NOT NULL DEFAULT '', platform TEXT NOT NULL, "
                "last_page INTEGER NOT NULL DEFAULT 1, last_run TEXT, "
                "PRIMARY KEY (keyword, city, salary, platform))"
            )
        except sqlite3.OperationalError:
            pass
        for ddl in (
            "ALTER TABLE scrape_sessions ADD COLUMN predicted_total INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE scrape_sessions ADD COLUMN scraped_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE scrape_sessions ADD COLUMN ttl_updated_at TEXT DEFAULT ''",
            "ALTER TABLE scrape_sessions ADD COLUMN exhausted_at TEXT DEFAULT ''",
            "ALTER TABLE scrape_sessions ADD COLUMN no_new_rounds INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass

    try:
        if not args.dry_run:
            try:
                # 先拿写锁，保证整个「读标准行/映射行 → 合并 → 删除映射行」原子完成
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as e:
                print(f"❌ 无法获取写锁（后端可能仍在运行）：{e}")
                return 3

        cols = _columns(conn)
        cfg = _load_config(conn)
        keywords = cfg["keywords"]
        if not keywords:
            print("ℹ️ 抓取配置里没有条件，无需迁移")
            return 0

        print(f"ℹ️ 当前配置 {len(keywords)} 组条件；只处理这些条件，已移除/改名的条件行保持原样。")
        migrated = 0
        for item in keywords:
            if isinstance(item, str):
                item = {"keyword": item}
            if not isinstance(item, dict):
                continue
            kw = str(item.get("keyword") or "").strip()
            if not kw:
                continue
            city = str(item.get("city") or "").strip() or cfg["default_city"]
            salary = str(item.get("salary") or "").strip() or cfg["default_salary"]
            for platform in PLATFORMS:
                native_kw = adapt_keyword(kw, platform)
                native_salary = map_salary(salary, platform)
                if native_kw == kw and native_salary == salary:
                    continue
                if _merge(
                    conn, cols,
                    (kw, city, salary, platform),
                    (native_kw, city, native_salary, platform),
                    args.dry_run,
                ):
                    migrated += 1
        if args.dry_run:
            print(f"\n✅ 预演完成：计划迁移 {migrated} 行（未写库）")
        else:
            conn.commit()
            print(f"\n✅ 迁移完成：已合并 {migrated} 行")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
