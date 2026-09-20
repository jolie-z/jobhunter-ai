#!/usr/bin/env python3
"""GitHub Traffic 历史存档脚本（仅标准库，无额外依赖）。

背景：GitHub Insights -> Traffic 只保留最近 14 天数据，过期即丢失。
本脚本每天拉取 views / clones 的逐日序列，按日期 upsert 合并进 CSV，
长期运行即可攒出超过 14 天的完整增长曲线，作为项目运营数据存档。

用法：
    export GITHUB_TOKEN=ghp_xxxx        # Personal Access Token，勾选 repo 权限
                                        # （traffic 接口只允许仓库 Owner 查询）
    python3 scripts/github_traffic_archive.py
    python3 scripts/github_traffic_archive.py --repo your-name/your-repo
    python3 scripts/github_traffic_archive.py --plot   # 存档后生成增长曲线 PNG

配合 cron 每天 9 点自动存档：
    0 9 * * * cd /你的项目路径 && /usr/bin/python3 scripts/github_traffic_archive.py >> scripts/traffic_data/cron.log 2>&1
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

API = "https://api.github.com"
DATA_DIR = Path(__file__).resolve().parent / "traffic_data"
CSV_FIELDS = ["date", "repo", "views", "views_unique", "clones", "clones_unique"]


def get_token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token.strip()
    # 尝试复用 gh CLI 的登录态（装了 gh 才有）
    try:
        out = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    sys.exit(
        "❌ 未找到 GITHUB_TOKEN。\n"
        "   请到 GitHub -> Settings -> Developer settings -> Personal access tokens\n"
        "   生成一个勾选 repo 权限的 token，然后执行：export GITHUB_TOKEN=ghp_xxxx"
    )


def fetch(token: str, path: str) -> dict:
    req = urllib.request.Request(
        f"{API}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "jobhunter-traffic-archiver",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def load_csv(csv_path: Path) -> dict:
    rows = {}
    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows[(row["date"], row["repo"])] = row
    return rows


def save_csv(csv_path: Path, rows: dict) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: (r["date"], r["repo"]))
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(ordered)


def archive_repo(token: str, repo: str, csv_path: Path) -> int:
    views = fetch(token, f"/repos/{repo}/traffic/views")
    clones = fetch(token, f"/repos/{repo}/traffic/clones")

    rows = load_csv(csv_path)
    added, updated = 0, 0
    for item in views.get("views", []):
        date = item["timestamp"][:10]
        key = (date, repo)
        row = rows.setdefault(
            key,
            {"date": date, "repo": repo, "views": "", "views_unique": "",
             "clones": "", "clones_unique": ""},
        )
        is_new = row["views"] == ""
        row["views"] = str(item["count"])
        row["views_unique"] = str(item["uniques"])
        added += is_new
        updated += not is_new
    for item in clones.get("clones", []):
        date = item["timestamp"][:10]
        key = (date, repo)
        row = rows.setdefault(
            key,
            {"date": date, "repo": repo, "views": "", "views_unique": "",
             "clones": "", "clones_unique": ""},
        )
        is_new = row["clones"] == ""
        row["clones"] = str(item["count"])
        row["clones_unique"] = str(item["uniques"])
        added += is_new
        updated += not is_new

    save_csv(csv_path, rows)
    print(
        f"✅ {repo}: 14天合计 views={views.get('count')} (unique {views.get('uniques')}), "
        f"clones={clones.get('count')} (unique {clones.get('uniques')})"
    )
    print(f"   CSV 新增 {added} 行 / 刷新 {updated} 行，共 {len(rows)} 行 -> {csv_path.name}")
    return len(rows)


def plot(csv_path: Path, repo: str) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("⚠️  未安装 matplotlib，跳过画图。可执行：pip install matplotlib")
        return

    rows = [r for r in load_csv(csv_path).values() if r["repo"] == repo and r["views"]]
    if not rows:
        print("⚠️  暂无数据可画图")
        return
    rows.sort(key=lambda r: r["date"])
    dates = [r["date"][5:] for r in rows]
    vu = [int(r["views_unique"]) for r in rows]
    cu = [int(r["clones_unique"] or 0) for r in rows]

    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    axes[0].plot(dates, vu, marker="o", color="#2ea043")
    axes[0].set_title(f"{repo} - daily unique visitors (archived)")
    axes[0].grid(alpha=0.3)
    axes[1].plot(dates, cu, marker="o", color="#58a6ff")
    axes[1].set_title("daily unique cloners (archived)")
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    out = csv_path.parent / f"traffic_{repo.replace('/', '_')}.png"
    fig.savefig(out, dpi=150)
    print(f"📈 曲线图已保存: {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="GitHub Traffic 历史存档")
    parser.add_argument("--repo", required=True,
                        help="要存档的仓库，格式 owner/name")
    parser.add_argument("--plot", action="store_true", help="存档后生成增长曲线图")
    args = parser.parse_args()

    token = get_token()
    csv_path = DATA_DIR / "github_traffic.csv"
    archive_repo(token, args.repo, csv_path)
    if args.plot:
        plot(csv_path, args.repo)
    print(f"   存档时间: {datetime.now().isoformat(timespec='seconds')}")


if __name__ == "__main__":
    main()
