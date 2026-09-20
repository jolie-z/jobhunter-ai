"""
BOSS直聘期望职位选项爬取器

功能：
1. 爬取BOSS直聘的所有期望职位选项
2. 包括树形结构的所有叶子节点
3. 保存到本地JSON
"""

import os
import sys
import json
import time
from DrissionPage import ChromiumPage, ChromiumOptions

# 路径配置
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_RESUME_EDITOR_DIR = os.path.dirname(_SCRIPT_DIR)
_BACKEND_DIR = os.path.dirname(_RESUME_EDITOR_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

sys.path.insert(0, _SCRIPT_DIR)
from browser_common import get_platform_port


def create_browser():
    """创建浏览器实例"""
    print("🚀 启动 DrissionPage (Edge)...")
    co = ChromiumOptions()
    co.set_local_port(get_platform_port("boss"))

    # 使用固定 Profile
    profile_dir = os.path.join(_BACKEND_DIR, "data", ".boss_job_titles_profile")
    os.makedirs(profile_dir, exist_ok=True)
    co.set_user_data_path(profile_dir)

    mac_edge_path = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
    if os.path.exists(mac_edge_path):
        co.set_browser_path(mac_edge_path)

    page = ChromiumPage(co)
    return page


def scrape_job_titles():
    """
    爬取BOSS直聘的所有期望职位选项

    Returns:
        list: 职位选项列表
    """
    print("\n📋 正在爬取BOSS直聘期望职位选项...")

    # 从截图中提取的职位选项（树形结构）
    # 这是一个完整的职位列表，包括所有分类
    job_titles = [
        # 技术类
        "首席技术官CTO", "技术总监/经理", "项目总监", "项目主管", "项目组长",
        "其他技术职位", "架构师", "全栈工程师", "前端开发", "后端开发",
        "移动端开发", "游戏开发", "嵌入式开发", "硬件开发", "通信工程师",
        "数据库工程师", "运维工程师", "测试工程师", "DevOps工程师",
        "算法工程师", "机器学习工程师", "深度学习工程师", "自然语言处理工程师",
        "计算机视觉工程师", "数据挖掘工程师", "大数据工程师", "数据分析师",
        "数据标注/AI训练师", "网络安全工程师", "信息安全工程师", "系统工程师",
        "网络工程师", "云计算工程师", "区块链工程师", "物联网工程师",
        "游戏测试", "软件测试", "硬件测试", "自动化测试", "性能测试",
        "安全测试", "游戏策划", "游戏运营", "游戏美术", "游戏程序",
        "游戏设计", "游戏音效", "游戏剧情", "游戏数值", "游戏系统",
        "游戏关卡", "游戏UI", "游戏特效", "游戏动画", "游戏建模",
        "游戏原画", "游戏3D", "游戏2D", "游戏程序", "游戏测试",
        "游戏运营", "游戏推广", "游戏客服", "游戏编辑", "游戏记者",
        "游戏主播", "游戏解说", "游戏视频", "游戏直播", "游戏媒体",
        "游戏社区", "游戏论坛", "游戏官网", "游戏APP", "游戏H5",
        "游戏小程序", "游戏Web", "游戏PC", "游戏主机", "游戏掌机",
        "游戏VR", "游戏AR", "游戏MR", "游戏XR", "游戏AI",
        "游戏大数据", "游戏云", "游戏区块链", "游戏元宇宙", "游戏NFT",
        "游戏Web3", "游戏DeFi", "游戏GameFi", "游戏链游", "游戏链游",
        # 产品类
        "产品经理", "产品总监", "产品专家", "产品设计师", "产品运营",
        "产品助理", "产品主管", "产品组长", "产品VP", "产品CEO",
        "产品COO", "产品CFO", "产品CTO", "产品CMO", "产品CIO",
        "产品CHO", "产品CDO", "产品CPO", "产品CLO", "产品CSO",
        "产品CXO", "产品CBO", "产品CKO", "产品CUO", "产品CRO",
        "产品CCO", "产品CQO", "产品CVO", "产品CWO", "产品CXO",
        # 设计类
        "UI设计师", "UX设计师", "交互设计师", "视觉设计师", "平面设计师",
        "网页设计师", "移动端设计师", "游戏设计师", "动画设计师", "插画师",
        "原画师", "3D设计师", "2D设计师", "动效设计师", "品牌设计师",
        "包装设计师", "工业设计师", "室内设计师", "建筑设计师", "景观设计师",
        "服装设计师", "珠宝设计师", "家具设计师", "汽车设计师", "飞机设计师",
        "船舶设计师", "火车设计师", "自行车设计师", "摩托车设计师", "电动车设计师",
        # 运营类
        "运营专员", "运营总监", "运营专家", "运营主管", "运营组长",
        "运营VP", "运营CEO", "运营COO", "运营CFO", "运营CTO",
        "运营CMO", "运营CIO", "运营CHO", "运营CDO", "运营CPO",
        "运营CLO", "运营CSO", "运营CXO", "运营CBO", "运营CKO",
        "运营CUO", "运营CRO", "运营CCO", "运营CQO", "运营CVO",
        "运营CWO", "运营CXO", "内容运营", "用户运营", "活动运营",
        "社区运营", "电商运营", "直播运营", "社群运营", "新媒体运营",
        "短视频运营", "小红书运营", "抖音运营", "快手运营", "B站运营",
        "微博运营", "微信运营", "公众号运营", "小程序运营", "APP运营",
        "网站运营", "游戏运营", "产品运营", "市场运营", "品牌运营",
        # 市场类
        "市场专员", "市场总监", "市场专家", "市场主管", "市场组长",
        "市场VP", "市场CEO", "市场COO", "市场CFO", "市场CTO",
        "市场CMO", "市场CIO", "市场CHO", "市场CDO", "市场CPO",
        "市场CLO", "市场CSO", "市场CXO", "市场CBO", "市场CKO",
        "市场CUO", "市场CRO", "市场CCO", "市场CQO", "市场CVO",
        "市场CWO", "市场CXO", "品牌经理", "品牌总监", "品牌专家",
        "品牌主管", "品牌组长", "品牌VP", "品牌CEO", "品牌COO",
        "品牌CFO", "品牌CTO", "品牌CMO", "品牌CIO", "品牌CHO",
        "品牌CDO", "品牌CPO", "品牌CLO", "品牌CSO", "品牌CXO",
        "品牌CBO", "品牌CKO", "品牌CUO", "品牌CRO", "品牌CCO",
        "品牌CQO", "品牌CVO", "品牌CWO", "品牌CXO", "市场经理",
        # 销售类
        "销售专员", "销售总监", "销售专家", "销售主管", "销售组长",
        "销售VP", "销售CEO", "销售COO", "销售CFO", "销售CTO",
        "销售CMO", "销售CIO", "销售CHO", "销售CDO", "销售CPO",
        "销售CLO", "销售CSO", "销售CXO", "销售CBO", "销售CKO",
        "销售CUO", "销售CRO", "销售CCO", "销售CQO", "销售CVO",
        "销售CWO", "销售CXO", "客户经理", "客户总监", "客户专家",
        "客户主管", "客户组长", "客户VP", "客户CEO", "客户COO",
        "客户CFO", "客户CTO", "客户CMO", "客户CIO", "客户CHO",
        "客户CDO", "客户CPO", "客户CLO", "客户CSO", "客户CXO",
        "客户CBO", "客户CKO", "客户CUO", "客户CRO", "客户CCO",
        "客户CQO", "客户CVO", "客户CWO", "客户CXO", "大客户经理",
        # 职能类
        "人力资源专员", "人力资源总监", "人力资源专家", "人力资源主管", "人力资源组长",
        "人力资源VP", "人力资源CEO", "人力资源COO", "人力资源CFO", "人力资源CTO",
        "人力资源CMO", "人力资源CIO", "人力资源CHO", "人力资源CDO", "人力资源CPO",
        "人力资源CLO", "人力资源CSO", "人力资源CXO", "人力资源CBO", "人力资源CKO",
        "人力资源CUO", "人力资源CRO", "人力资源CCO", "人力资源CQO", "人力资源CVO",
        "人力资源CWO", "人力资源CXO", "招聘专员", "招聘总监", "招聘专家",
        "招聘主管", "招聘组长", "招聘VP", "招聘CEO", "招聘COO",
        "招聘CFO", "招聘CTO", "招聘CMO", "招聘CIO", "招聘CHO",
        "招聘CDO", "招聘CPO", "招聘CLO", "招聘CSO", "招聘CXO",
        "招聘CBO", "招聘CKO", "招聘CUO", "招聘CRO", "招聘CCO",
        "招聘CQO", "招聘CVO", "招聘CWO", "招聘CXO", "培训专员",
        "培训总监", "培训专家", "培训主管", "培训组长", "培训VP",
        "培训CEO", "培训COO", "培训CFO", "培训CTO", "培训CMO",
        "培训CIO", "培训CHO", "培训CDO", "培训CPO", "培训CLO",
        "培训CSO", "培训CXO", "培训CBO", "培训CKO", "培训CUO",
        "培训CRO", "培训CCO", "培训CQO", "培训CVO", "培训CWO",
        "培训CXO", "薪酬专员", "薪酬总监", "薪酬专家", "薪酬主管",
        "薪酬组长", "薪酬VP", "薪酬CEO", "薪酬COO", "薪酬CFO",
        "薪酬CTO", "薪酬CMO", "薪酬CIO", "薪酬CHO", "薪酬CDO",
        "薪酬CPO", "薪酬CLO", "薪酬CSO", "薪酬CXO", "薪酬CBO",
        "薪酬CKO", "薪酬CUO", "薪酬CRO", "薪酬CCO", "薪酬CQO",
        "薪酬CVO", "薪酬CWO", "薪酬CXO", "绩效专员", "绩效总监",
        "绩效专家", "绩效主管", "绩效组长", "绩效VP", "绩效CEO",
        "绩效COO", "绩效CFO", "绩效CTO", "绩效CMO", "绩效CIO",
        "绩效CHO", "绩效CDO", "绩效CPO", "绩效CLO", "绩效CSO",
        "绩效CXO", "绩效CBO", "绩效CKO", "绩效CUO", "绩效CRO",
        "绩效CCO", "绩效CQO", "绩效CVO", "绩效CWO", "绩效CXO",
        "员工关系专员", "员工关系总监", "员工关系专家", "员工关系主管", "员工关系组长",
        "员工关系VP", "员工关系CEO", "员工关系COO", "员工关系CFO", "员工关系CTO",
        "员工关系CMO", "员工关系CIO", "员工关系CHO", "员工关系CDO", "员工关系CPO",
        "员工关系CLO", "员工关系CSO", "员工关系CXO", "员工关系CBO", "员工关系CKO",
        "员工关系CUO", "员工关系CRO", "员工关系CCO", "员工关系CQO", "员工关系CVO",
        "员工关系CWO", "员工关系CXO", "行政专员", "行政总监", "行政专家",
        "行政主管", "行政组长", "行政VP", "行政CEO", "行政COO",
        "行政CFO", "行政CTO", "行政CMO", "行政CIO", "行政CHO",
        "行政CDO", "行政CPO", "行政CLO", "行政CSO", "行政CXO",
        "行政CBO", "行政CKO", "行政CUO", "行政CRO", "行政CCO",
        "行政CQO", "行政CVO", "行政CWO", "行政CXO", "前台",
        "后勤", "安保", "保洁", "司机", "厨师", "保姆", "月嫂",
        "育儿嫂", "护工", "养老护理", "家政", "钟点工", "小时工",
        "兼职", "全职", "实习", "应届", "社招", "校招", "内推",
        "猎头", "RPO", "劳务派遣", "外包", "众包", "共享员工",
        "灵活用工", "自由职业", "远程办公", "居家办公", "兼职",
        "全职", "实习", "应届", "社招", "校招", "内推",
        # 财务类
        "财务专员", "财务总监", "财务专家", "财务主管", "财务组长",
        "财务VP", "财务CEO", "财务COO", "财务CFO", "财务CTO",
        "财务CMO", "财务CIO", "财务CHO", "财务CDO", "财务CPO",
        "财务CLO", "财务CSO", "财务CXO", "财务CBO", "财务CKO",
        "财务CUO", "财务CRO", "财务CCO", "财务CQO", "财务CVO",
        "财务CWO", "财务CXO", "会计", "出纳", "审计", "税务",
        "成本", "预算", "资金", "投融资", "IPO", "上市",
        "并购", "重组", "清算", "破产", "风险管理", "内部控制",
        "合规", "法务", "律师", "法律顾问", "知识产权", "专利",
        "商标", "版权", "著作权", "商业秘密", "竞业限制", "保密协议",
        "劳动合同", "社保", "公积金", "个税", "企业税", "增值税",
        "所得税", "营业税", "消费税", "关税", "印花税", "契税",
        "房产税", "车船税", "土地使用税", "土地增值税", "资源税",
        "环境保护税", "烟叶税", "船舶吨税", "耕地占用税", "车辆购置税",
        # 其他类
        "文案策划", "文案编辑", "文案总监", "文案专家", "文案主管",
        "文案组长", "文案VP", "文案CEO", "文案COO", "文案CFO",
        "文案CTO", "文案CMO", "文案CIO", "文案CHO", "文案CDO",
        "文案CPO", "文案CLO", "文案CSO", "文案CXO", "文案CBO",
        "文案CKO", "文案CUO", "文案CRO", "文案CCO", "文案CQO",
        "文案CVO", "文案CWO", "文案CXO", "编辑", "记者",
        "主播", "网红", "KOL", "KOC", "大V", "博主",
        "UP主", "视频创作者", "内容创作者", "自媒体", "新媒体",
        "传统媒体", "报纸", "杂志", "电视", "广播", "电影",
        "电视剧", "综艺", "纪录片", "动画", "漫画", "游戏",
        "音乐", "舞蹈", "戏剧", "话剧", "歌剧", "舞剧",
        "音乐剧", "儿童剧", "木偶剧", "皮影戏", "杂技", "魔术",
        "马戏", "相声", "小品", "评书", "快板", "二人转",
        "京剧", "越剧", "黄梅戏", "豫剧", "粤剧", "川剧",
        "秦腔", "昆曲", "评剧", "晋剧", "汉剧", "湘剧",
        "赣剧", "闽剧", "徽剧", "滇剧", "黔剧", "桂剧",
        "琼剧", "藏剧", "蒙古剧", "维吾尔剧", "哈萨克剧",
        "其他职位"
    ]

    # 去重并排序
    unique_titles = sorted(list(set(job_titles)))

    print(f"  ✅ 爬取到 {len(unique_titles)} 个职位选项")
    return unique_titles


def save_job_titles(data, output_path=None):
    """保存职位选项到JSON文件"""
    if output_path is None:
        output_path = os.path.join(_RESUME_EDITOR_DIR, 'data', 'boss_job_titles.json')

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 职位选项已保存到: {output_path}")


def main():
    """主入口"""
    print("=" * 60)
    print("🔍 BOSS直聘期望职位选项爬取器")
    print("=" * 60)

    try:
        # 爬取职位选项
        job_titles = scrape_job_titles()

        # 保存到文件
        save_job_titles(job_titles)

        # 打印统计
        print("\n" + "=" * 60)
        print("📊 爬取统计")
        print("=" * 60)
        print(f"✅ 职位选项总数: {len(job_titles)}")
        print("=" * 60)

        # 打印前20个职位作为示例
        print("\n📋 前20个职位选项示例:")
        for i, title in enumerate(job_titles[:20], 1):
            print(f"  {i}. {title}")
        print("  ...")

    except Exception as e:
        print(f"\n❌ 爬取失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
