"""resume_editor 子系统数据路径单一事实源。

背景（模块五质检 Q-M5-2，2026-09-20）：platforms 子系统此前各自用
`os.path.dirname(__file__)/..` 自算 data 目录，路径逻辑四处漂移，导致
测试无法通过单一 patch 隔离（SnapshotManager 默认参数甚至在类定义时
绑定生产路径）。新代码一律 `from resume_editor.paths import DATA_DIR`；
历史一次性采集脚本的常量按「触碰才还」逐步收敛。

注意：DATA_DIR 指向 backend/resume_editor/data（整个 data/ 已 gitignore）。
"""
import os

RESUME_EDITOR_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(RESUME_EDITOR_DIR, "data")
SNAPSHOTS_DIR = os.path.join(DATA_DIR, "snapshots")
