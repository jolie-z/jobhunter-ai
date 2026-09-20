"""browser_common 端口红线回归（承接自被删的游离测试，2026-09-20 用户裁决删游离+承接重建）。

红线：端口无响应必须报错，绝不自动拉起浏览器（防 DrissionPage 拉起默认 Chrome 事故）。
"""
import sys
import unittest
from unittest import mock

sys.path.insert(0, ".")

import resume_editor.platforms.browser_common as browser_common
from resume_editor.platforms.browser_common import EDGE_PATH, connect_page, ensure_port_ready, make_options


class TestEnsurePortReady(unittest.TestCase):
    def test_port_ready_ok(self):
        """端口有 CDP 响应：不抛异常"""
        with mock.patch.object(browser_common._no_proxy_opener, "open", return_value=mock.MagicMock()):
            ensure_port_ready(19999)

    def test_port_down_raises(self):
        """端口无响应：必须抛 RuntimeError 并提示先启动 Edge（绝不静默拉起浏览器）"""
        def _boom(*a, **k):
            raise OSError("Connection refused")
        with mock.patch.object(browser_common._no_proxy_opener, "open", side_effect=_boom):
            with self.assertRaises(RuntimeError) as ctx:
                ensure_port_ready(19999)
        self.assertIn("19999", str(ctx.exception))
        self.assertIn("Edge", str(ctx.exception))

    def test_connect_page_port_down_raises(self):
        """connect_page 在端口无响应时抛错，绝不让 ChromiumPage 有机会自动启动"""
        def _boom(*a, **k):
            raise OSError("Connection refused")
        with mock.patch.object(browser_common._no_proxy_opener, "open", side_effect=_boom):
            with self.assertRaises(RuntimeError):
                connect_page(19999)

    def test_connect_page_ok_uses_edge_path(self):
        """端口正常时：ChromiumOptions 必须显式指定 Edge 路径（防 Chrome 拉起）"""
        with mock.patch.object(browser_common._no_proxy_opener, "open", return_value=mock.MagicMock()):
            with mock.patch("DrissionPage.ChromiumPage", return_value="page") as cp:
                page = connect_page(19999)
                self.assertEqual(page, "page")
                self.assertIn(EDGE_PATH, str(cp.call_args[0][0].__dict__))

    def test_make_options_has_edge_path(self):
        self.assertIn(EDGE_PATH, str(make_options(19999).__dict__))


if __name__ == "__main__":
    unittest.main(verbosity=2)
