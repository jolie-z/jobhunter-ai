import pytest
import sys
import json
import urllib.request
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from resume_editor.platforms.boss_write_back import PORT


_no_proxy_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def is_edge_port_open() -> bool:
    """探测 BOSS 专属 Edge 浏览器 19222 端口是否在线"""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/json/version")
        with _no_proxy_opener.open(req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


class TestBossE2ELive:
    """BOSS 直聘全链路真实浏览器与官网接口真机 E2E 测试套件"""

    @pytest.mark.skipif(not is_edge_port_open(), reason=f"Edge 浏览器专属端口 {PORT} 未启动，跳过真机 E2E")
    def test_01_live_browser_preview_and_skills_e2e(self):
        """真实连接 19222 端口，回读官网在线简历，验证工作经历技能 emphasis 与隐私状态"""
        from DrissionPage import ChromiumPage, ChromiumOptions
        from resume_editor.platforms.boss_write_back import (
            load_preview_and_tokens,
            fetch_json_api,
        )

        co = ChromiumOptions().set_address(f"127.0.0.1:{PORT}")
        page = ChromiumPage(addr_or_opts=co)
        assert page is not None, "必须成功连接到真实浏览器页面"

        official_zp, tokens = load_preview_and_tokens(page)
        assert official_zp is not None, "必须能正常拉取官网在线简历 JSON"
        assert tokens.get("zp_token") or tokens.get("token"), "必须能提取有效鉴权 token"

        # 验证官网工作经历列表结构
        work_list = official_zp.get("workExpList", [])
        assert isinstance(work_list, list), "官网 workExpList 必须为列表"
        if work_list:
            first_work = work_list[0]
            # 断言拥有技能 emphasis 字段格式（官网回读为 string 数组或 string）
            emphasis = first_work.get("emphasis")
            assert emphasis is not None, "工作经历中必须存在 emphasis 字段"
            if isinstance(emphasis, list) and len(emphasis) > 0:
                print(f"  [E2E 验证成功] 官网首条工作经历拥有技能标签: {emphasis}")
            elif isinstance(emphasis, str) and emphasis:
                print(f"  [E2E 验证成功] 官网首条工作经历拥有技能字符串: {emphasis}")

            # 断言隐藏简历字段
            assert "isPublic" in first_work, "工作经历中必须存在 isPublic 隐私字段"
            print(f"  [E2E 验证成功] 官网首条工作经历隐藏状态 isPublic = {first_work.get('isPublic')}")

    @pytest.mark.skipif(not is_edge_port_open(), reason=f"Edge 浏览器专属端口 {PORT} 未启动，跳过真机 E2E")
    def test_02_live_browser_dry_run_full_schedule(self):
        """在真实浏览器环境中执行全模块 Dry-Run 编排，确保无任何未声明变量或语法异常"""
        from resume_editor.platforms.boss_write_back import run_write_back

        # 执行 dry_run 模拟回写
        result = run_write_back(dry_run=True)
        # dry_run 返回 0 或正常字典
        assert result == 0 or isinstance(result, dict) or result is None
