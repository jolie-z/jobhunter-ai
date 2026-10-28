"""可写路径统一解析 —— JOBHUNTER_DATA_DIR 收口阀门（M2）+ 单文件 env 阀门（M1/先例）。

背景：打包分发形态（Electron 安装到 /Applications、Program Files）中仓库目录只读，
所有运行时可写文件必须落到用户数据目录（壳注入 JOBHUNTER_DATA_DIR = Electron userData）。

优先级（每处路径）：
  1. 单文件显式 env（JOBHUNTER_DB_PATH / AUTOPILOT_DB_PATH / ...）——侧车/双实例铁律先例；
  2. JOBHUNTER_DATA_DIR/<subpath> —— 打包形态统一收口；
  3. 历史默认锚点 —— 开发形态逐字保持（backend/data 与仓根 data 双锚点现状，业务零改动）。

先例：AUTOPILOT_DB_PATH（373d866e）、JOBHUNTER_DB_PATH（M1 子项②）。
"""
import os
from pathlib import Path
from typing import TypeVar

_PathLike = TypeVar("_PathLike", str, Path)


def jobhunter_data_dir() -> Path | None:
    """打包形态的用户数据目录（壳注入）；未设置 = 开发形态，返回 None。"""
    value = os.environ.get("JOBHUNTER_DATA_DIR", "")
    return Path(value) if value.strip() else None


def writable_path(default: _PathLike, subpath: str, env_var: str | None = None) -> _PathLike:
    """按优先级解析单个可写路径；返回类型与传入默认值同型（str→str / Path→Path）。"""
    if env_var:
        override = os.environ.get(env_var, "")
        if override.strip():
            return Path(override) if isinstance(default, Path) else override
    data_dir = jobhunter_data_dir()
    if data_dir is not None:
        target = data_dir / subpath
        target.parent.mkdir(parents=True, exist_ok=True)
        return target if isinstance(default, Path) else str(target)
    return default


def job_hunter_db_path(default: _PathLike) -> _PathLike:
    """主库路径：JOBHUNTER_DB_PATH > JOBHUNTER_DATA_DIR/job_hunter.db > 历史锚点。"""
    return writable_path(default, "job_hunter.db", env_var="JOBHUNTER_DB_PATH")
