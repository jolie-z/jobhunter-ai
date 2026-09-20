"""
平台简历编辑器基类
"""

from abc import ABC, abstractmethod


class BaseResumeEditor(ABC):
    """简历编辑器基类"""

    @abstractmethod
    def get_resume_fields(self) -> dict:
        """获取简历所有字段"""
        pass

    @abstractmethod
    def update_resume(self, data: dict) -> bool:
        """更新简历"""
        pass
