import urllib.parse

import requests

from app.core.config import settings


def get_amap_navigation_url(address: str) -> str:
    """调用高德Web服务API，将文本地址转为精确的经纬度导航链接"""
    encoded_name = urllib.parse.quote(address)
    fallback_url = f"https://uri.amap.com/search?keyword={encoded_name}"

    if not settings.AMAP_API_KEY:
        print("  [⚠️] 未配置 AMAP_API_KEY，降级使用基础搜索链接")
        return fallback_url

    try:
        # 使用配置文件中的 BASE_URL
        params = {"address": address, "key": settings.AMAP_API_KEY}
        resp = requests.get(settings.AMAP_BASE_URL, params=params, timeout=3).json()

        # 严格解析高德返回的真实经纬度坐标
        if str(resp.get("status")) == "1" and int(resp.get("count", 0)) > 0:
            location = resp["geocodes"][0]["location"] # 格式: "113.32,23.10"

            # 🌟 核心杀手锏：使用 navigation 协议！
            # 有APP瞬间唤起，无APP则用飞书浏览器完美渲染动态路线图
            return f"https://uri.amap.com/navigation?to={location},{encoded_name}&mode=transit"

    except Exception as e:
        print(f"  [❌] 高德原生API解析异常: {e}")

    # 如果发生任何异常（断网、限流），安全降级
    return fallback_url
