"""resume_editor 子系统数据路径单一事实源。

背景（模块五质检 Q-M5-2，2026-09-20）：platforms 子系统此前各自用
`os.path.dirname(__file__)/..` 自算 data 目录，路径逻辑四处漂移，导致
测试无法通过单一 patch 隔离。新代码一律 `from resume_editor.paths import …`。

读/写锚点拆分（2026-10-26，0.3.2～0.3.5 个人数据随安装包泄漏 + 自动更新清空用户数据事故）：
- DICT_DIR  只读平台字典（城市/行业/证书/选项表），git 跟踪、随包分发，任何运行时代码不得写入；
- DATA_DIR  运行时用户数据（四平台 *_fields.json 简历内容、*_writeback.json、快照、写回日志、
  映射报告、学习缓存）。打包态经 db_paths 阀门落 JOBHUNTER_DATA_DIR/resume_editor（安装目录在
  自动更新时被整体替换，绝不能落那里）；开发态无 env 时逐字保持历史锚点 resume_editor/data。
- 两者过去混在同一目录，字典只有 9 个在 git 里、其余只在构建机上，用户简历 dump 则随包分发。

导入约定：全仓统一 `from resume_editor.paths import …`，禁止裸 `import paths`（同进程双模块实例）。
子进程脚本（platforms/*.py 独立拉起时 sys.path[0] 只有 platforms/）必须先把 backend 根插入
sys.path 再导入本模块——下方自举只保证本模块内部能 import app.core.db_paths，救不了导入本模块那一步。
"""
import os
import sys

RESUME_EDITOR_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(RESUME_EDITOR_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.core.db_paths import writable_path  # noqa: E402  app/__init__.py 为空，导入零副作用

DICT_DIR = os.path.join(RESUME_EDITOR_DIR, "dicts")
DATA_DIR: str = writable_path(os.path.join(RESUME_EDITOR_DIR, "data"), "resume_editor")
SNAPSHOTS_DIR = os.path.join(DATA_DIR, "snapshots")
SCHEMA_SNAPSHOTS_DIR = os.path.join(DATA_DIR, "schema_snapshots")
WRITEBACK_LOGS_DIR = os.path.join(DATA_DIR, "writeback_logs")
UNIFIED_PATH = os.path.join(DATA_DIR, "unified_resume.json")

PLATFORMS = ("boss", "liepin", "51job", "zhilian")


def dict_path(name: str) -> str:
    """只读字典文件路径（随包）。"""
    return os.path.join(DICT_DIR, name)


def fields_path(platform: str) -> str:
    """平台采集/编辑后的简历字段文件（用户数据）。"""
    return os.path.join(DATA_DIR, f"{platform}_fields.json")


def writeback_path(platform: str) -> str:
    """平台回写快照（用户数据）。"""
    return os.path.join(DATA_DIR, f"{platform}_writeback.json")


def option_source_path(spec_file: str, data_dir: str | None = None, dict_dir: str | None = None) -> str:
    """选项表数据源分发：agent_mapper._OPTION_FILES 里唯一的用户数据项是 boss_fields.json@genders
    （从用户已采集的字段里取性别枚举），其余全是字典。按文件名后缀分流，不在巨石文件里散落判定。
    兼容原始 spec 串（"a.json#key" / "a.json@extractor"），先剥离修饰符再判断。
    data_dir/dict_dir 可由调用方显式传入（使测试 patch 调用方模块属性仍然生效），缺省用本模块常量。"""
    name = spec_file.split("@", 1)[0].split("#", 1)[0]
    if name.endswith("_fields.json"):
        return os.path.join(data_dir or DATA_DIR, name)
    return os.path.join(dict_dir or DICT_DIR, name)


def ensure_data_dir() -> str:
    """预建用户数据目录及三个子目录（幂等）。打包态全新安装时这些目录都不存在，
    写入方若直接 open() 会 FileNotFoundError。"""
    for d in (DATA_DIR, SNAPSHOTS_DIR, SCHEMA_SNAPSHOTS_DIR, WRITEBACK_LOGS_DIR):
        os.makedirs(d, exist_ok=True)
    return DATA_DIR
