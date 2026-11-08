"""简历照片单一可信源注入。

「照片」附件字段是用户当前照片的唯一权威来源；「结构化数据」JSON 里的
personalInfo.avatar_url 是历史保存时烘焙的快照（首次上传后即固化，后续
换照片不更新它），渲染取值链路又普遍 personalInfo.avatar_url 优先，导致
换照片后物料永远渲染第一张。统一在渲染入口用附件字段覆写旧值。

所有渲染出口（打印路由 get_resume_data / 本地兜底引擎 build_resume_html
的调用方 / 精投定制缝合）必须共用本函数，禁止各自内联实现同名逻辑。
"""
from __future__ import annotations

from typing import Any

from app.core.config import settings


def extract_photo_url(field_val: Any) -> str:
    """从飞书「照片」附件字段的原始值解析出代理图片 URL，无附件返回空串。"""
    if not field_val or not isinstance(field_val, list):
        return ""
    first_item = field_val[0]
    if isinstance(first_item, dict):
        file_token = first_item.get("file_token")
        if file_token:
            return f"{settings.BACKEND_BASE_URL.rstrip('/')}/api/strategy/avatar/{file_token}"
    return ""


def _strip_personal_avatar(personal: Any) -> None:
    if isinstance(personal, dict):
        personal.pop("avatar_url", None)


def _strip_top_level_avatar(data: dict[str, Any]) -> None:
    data.pop("avatar_url", None)


def apply_feishu_avatar(resume_data: dict[str, Any], avatar_url: str) -> None:
    """把「照片」附件字段解析出的 URL 写进简历数据，并清掉全部历史旧值。

    - avatar_url 非空：写入 personalInfo.avatar_url 与顶层 avatar_url（双写，
      兼容两类取值模板：personalInfo 优先系 / data.avatar_url 系）
    - avatar_url 为空串（调用方已确认当前无照片，用户删了照片或字段为空）：
      清除两处旧值，避免「删了照片物料里还在」的反向不一致
    - 「照片字段读取失败」的调用方（feishu_service.get_resume_photo_url 返回
      None）必须自行短路，不得把 None 传进来——读取失败应按烘焙值渲染
    - resume_data 非法或无 personalInfo 结构时只做顶层兜底，不凭空造结构
    """
    if not isinstance(resume_data, dict):
        return

    personal = resume_data.get("personalInfo")
    if not isinstance(personal, dict):
        # 结构缺失时绝不凭空造 personalInfo（下游模板按其存在性分支渲染）
        if avatar_url:
            resume_data["avatar_url"] = avatar_url
        else:
            _strip_top_level_avatar(resume_data)
        return

    if avatar_url:
        personal["avatar_url"] = avatar_url
        resume_data["avatar_url"] = avatar_url
    else:
        _strip_personal_avatar(personal)
        _strip_top_level_avatar(resume_data)


def strip_baked_avatar(resume_data: dict[str, Any]) -> None:
    """只清除结构化数据里烘焙的历史照片 URL，不注入新值。

    供「照片字段读取不便」的渲染链路（如精投定制缝合）使用：剔除旧值后
    渲染模板按缺照片处理，或由调用方随后 apply_feishu_avatar 注入新值。
    """
    if not isinstance(resume_data, dict):
        return
    _strip_personal_avatar(resume_data.get("personalInfo"))
    _strip_top_level_avatar(resume_data)
