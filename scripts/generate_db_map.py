#!/usr/bin/env python3
"""生成《JobHunter 数据模型全景》页面（仓库根目录 sqlite_database_relationship_map.html）。

数据来源分两层：
- 结构层（实时）：以只读模式打开 4 个本地 SQLite 文件，读 sqlite_master / PRAGMA table_info /
  PRAGMA index_list / COUNT(*)——表、字段、索引、行数永远反映当前真实结构；
- 注释层（人工维护）：scripts/db_map_annotations.json 里的领域归属、表/字段中文描述与关系清单。
  新加的表即使没有注释也会出现在页面上（领域标记为「未分类」），保证结构层不过期。

用法：
  python3 scripts/generate_db_map.py            # 完整版（含行数快照）
  python3 scripts/generate_db_map.py --public   # 公开脱敏版：剔除行数等运行时数据
"""

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = Path(__file__).resolve().parent / "db_map_template.html"
ANNOTATIONS_PATH = Path(__file__).resolve().parent / "db_map_annotations.json"
OUTPUT_PATH = REPO_ROOT / "sqlite_database_relationship_map.html"

# 相对仓库根目录的数据库文件（页面上也按此相对路径展示，不暴露本机绝对路径）
DATABASES = [
    ("job_hunter.db", "backend/data/job_hunter.db"),
    ("autopilot.db", "backend/autopilot.db"),
    ("sessions.db", "backend/data/sessions.db"),
    ("langgraph_checkpoints.db", "backend/langgraph_checkpoints.db"),
]

UNCLASSIFIED_DOMAIN = "Uncategorized (未分类)"


def read_live_schema(db_path: Path) -> dict:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = {}
        names = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        for name in names:
            columns = []
            for col in con.execute(f'PRAGMA table_info("{name}")'):
                cid, cname, ctype, notnull, dflt, pk = col
                columns.append(
                    {
                        "name": cname,
                        "type": ctype,
                        "notnull": bool(notnull),
                        "default": dflt,
                        "pk": bool(pk),
                    }
                )
            indexes = [
                {"name": row[1], "unique": bool(row[2])}
                for row in con.execute(f'PRAGMA index_list("{name}")')
            ]
            rows = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            tables[name] = {"columns": columns, "indexes": indexes, "rows": rows}
        return tables
    finally:
        con.close()


def build_db_data(annotations: dict, public: bool) -> tuple[dict, list[str], int]:
    warnings = []
    undocumented_columns = 0
    table_annos = annotations.get("tables", {})
    db_data = {}
    for db_name, rel_path in DATABASES:
        abs_path = REPO_ROOT / rel_path
        if not abs_path.exists():
            raise SystemExit(f"找不到数据库文件：{abs_path}")
        live_tables = read_live_schema(abs_path)

        merged = {}
        for tname, live in live_tables.items():
            anno = table_annos.get(tname)
            if anno is None:
                warnings.append(f"{db_name}: 新表 {tname} 无注释，已标记为「未分类」")
                anno = {"domain": UNCLASSIFIED_DOMAIN, "desc": "", "columns": {}}
            col_annos = anno.get("columns", {})
            undocumented_columns += sum(1 for c in live["columns"] if c["name"] not in col_annos)
            table = {
                "name": tname,
                "db": db_name,
                "domain": anno.get("domain", UNCLASSIFIED_DOMAIN),
                "desc": anno.get("desc", ""),
                "columns": [{**c, "desc": col_annos.get(c["name"], "")} for c in live["columns"]],
                "indexes": live["indexes"],
            }
            if not public:
                table["rows"] = live["rows"]
            merged[tname] = table

        db_data[db_name] = {"file": rel_path, "tables": merged}
    return db_data, warnings, undocumented_columns


def check_stale_annotations(annotations: dict, db_data: dict) -> list[str]:
    warnings = []
    live_all = set()
    for db in db_data.values():
        live_all.update(db["tables"])
    for tname in annotations.get("tables", {}):
        if tname not in live_all:
            warnings.append(f"注释层中的表 {tname} 在任何真实库里都不存在，请确认是否已删除")
    live_rels = live_all
    for rel in annotations.get("relationships", []):
        missing = [rel["source"], rel["target"]]
        for m in missing:
            if m not in live_rels:
                warnings.append(f"关系线引用了不存在的表 {m}（{rel['source']} → {rel['target']}）")
    return warnings


def compute_stats(db_data: dict, relationships: list) -> dict:
    dbs = len(db_data)
    tables = sum(len(db["tables"]) for db in db_data.values())
    columns = sum(
        len(t["columns"]) for db in db_data.values() for t in db["tables"].values()
    )
    return {"dbs": dbs, "tables": tables, "relations": len(relationships), "columns": columns}


def inject(template: str, replacements: dict) -> str:
    out = template
    for key, value in replacements.items():
        out = out.replace(key, value)
    return out


def to_js(value) -> str:
    """注入 <script> 的 JSON；转义 </ 防止提前闭合脚本标签。"""
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def main() -> None:
    public = "--public" in sys.argv
    annotations = json.loads(ANNOTATIONS_PATH.read_text(encoding="utf-8"))
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    db_data, warnings, undocumented = build_db_data(annotations, public)
    warnings += check_stale_annotations(annotations, db_data)
    relationships = annotations.get("relationships", [])
    stats = compute_stats(db_data, relationships)

    html = inject(
        template,
        {
            "__DB_DATA__": to_js(db_data),
            "__RELATIONSHIPS__": to_js(relationships),
            "__DOMAIN_COLORS__": to_js(annotations.get("domains", {})),
            "__GENERATED_AT__": date.today().isoformat(),
            "__STATS__": to_js(stats),
            "__IS_PUBLIC__": "true" if public else "false",
        },
    )
    OUTPUT_PATH.write_text(html, encoding="utf-8")

    mode = "公开脱敏版（不含行数）" if public else "完整版（含行数快照）"
    print(f"已生成 {OUTPUT_PATH.relative_to(REPO_ROOT)}（{mode}）")
    print(
        f"统计：{stats['dbs']} 个数据库 / {stats['tables']} 张表 / "
        f"{stats['columns']} 个字段 / {stats['relations']} 条关系"
    )
    if undocumented:
        print(f"提示：{undocumented} 个字段暂无中文描述，可在 {ANNOTATIONS_PATH.name} 的 tables.<表名>.columns 中补充")
    if warnings:
        print(f"\n{len(warnings)} 条结构提示（需人工处理）：")
        for w in warnings:
            print(f"  - {w}")


if __name__ == "__main__":
    main()
