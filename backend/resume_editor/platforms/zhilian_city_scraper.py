"""
智联招聘城市三级数据爬取 - 精确版
基于 s-cascader 组件结构: li.s-cascader__option
"""
import json
import time
import os
import sys
from DrissionPage import ChromiumPage, ChromiumOptions

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_RESUME_EDITOR_DIR = os.path.dirname(_SCRIPT_DIR)
_DATA_DIR = os.path.join(_RESUME_EDITOR_DIR, "data")

sys.path.insert(0, _SCRIPT_DIR)
from browser_common import get_platform_port


def create_browser():
    co = ChromiumOptions()
    co.set_local_port(get_platform_port("zhilian"))
    page = ChromiumPage(co)
    return page


def get_cascader_columns(tab):
    """获取当前cascader中所有列的选项"""
    return tab.run_js("""
    return (function(){
        var columns = document.querySelectorAll('.s-cascader__options');
        var result = [];
        for(var i=0; i<columns.length; i++){
            var col = columns[i];
            if(col.offsetWidth === 0) continue;
            var options = col.querySelectorAll('.s-cascader__option');
            var items = [];
            for(var j=0; j<options.length; j++){
                var opt = options[j];
                items.push({
                    text: opt.textContent.trim(),
                    isActive: opt.className.indexOf('is-active') > -1,
                    hasChildren: opt.querySelector('.s-cascader__option-arrow') !== null || opt.className.indexOf('has-children') > -1
                });
            }
            result.push(items);
        }
        return result;
    })();
    """)


def scrape_all_cities(tab):
    """爬取完整的省→市→区三级数据"""
    # 先打开城市选择器 - 点击"现居住城市"区域
    print("打开城市选择器...")

    # 找到现居住城市的可点击区域
    clicked = tab.run_js("""
    return (function(){
        // 找到"现居住城市"标签
        var labels = document.querySelectorAll('span, div, label');
        for(var i=0; i<labels.length; i++){
            if(labels[i].textContent.trim() === '现居住城市' && labels[i].children.length === 0){
                // 找到同行的选择器区域
                var row = labels[i].closest('.resume-item') || labels[i].parentElement.parentElement;
                if(row){
                    var clickable = row.querySelector('[class*=city], [class*=select], [class*=cascader], [class*=area]');
                    if(clickable){
                        clickable.click();
                        return 'clicked: ' + clickable.className;
                    }
                    // 尝试点击行内的span/div
                    var spans = row.querySelectorAll('span, div');
                    for(var j=0; j<spans.length; j++){
                        if(spans[j].textContent.indexOf('广东') > -1 || spans[j].textContent.indexOf('广州') > -1){
                            spans[j].click();
                            return 'clicked span: ' + spans[j].textContent.trim();
                        }
                    }
                }
                return 'found label but no clickable';
            }
        }
        return 'label not found';
    })();
    """)
    print(f"Click result: {clicked}")
    time.sleep(1)

    # 检查modal是否出现
    modal_visible = tab.run_js("""
    return (function(){
        var dialog = document.querySelector('.s-dialog[aria-label="请选择行政区"]');
        if(dialog && dialog.offsetWidth > 0) return true;
        // 也检查display
        var dialogs = document.querySelectorAll('.s-dialog');
        for(var i=0; i<dialogs.length; i++){
            if(dialogs[i].textContent.indexOf('请选择行政区') > -1 && dialogs[i].offsetWidth > 0) return true;
        }
        return false;
    })();
    """)

    if not modal_visible:
        print("Modal未出现，尝试直接点击...")
        # 用DrissionPage原生点击
        el = tab.ele('text:现居住城市')
        if el:
            parent = el.parent()
            if parent:
                parent.click()
                time.sleep(1)
        # 再检查
        modal_visible = tab.run_js("""
        return (function(){
            var dialogs = document.querySelectorAll('.s-dialog');
            for(var i=0; i<dialogs.length; i++){
                if(dialogs[i].textContent.indexOf('请选择行政区') > -1 && dialogs[i].offsetWidth > 0) return true;
            }
            return false;
        })();
        """)

    if not modal_visible:
        print("ERROR: 无法打开城市选择器")
        tab.get_screenshot(path=os.path.join(_DATA_DIR, "zhilian_city_debug2.png"))
        return None

    print("城市选择器已打开!")

    # 获取第一列（省份）
    columns = get_cascader_columns(tab)
    if not columns or len(columns) == 0:
        print("ERROR: 未找到cascader列")
        return None

    provinces = columns[0]
    print(f"找到 {len(provinces)} 个省份/区域")

    all_data = []

    for pi, prov in enumerate(provinces):
        prov_name = prov['text']
        print(f"\n[{pi+1}/{len(provinces)}] 省份: {prov_name}")

        # 点击省份
        tab.run_js(f"""
        (function(){{
            var columns = document.querySelectorAll('.s-cascader__options');
            if(columns.length === 0) return;
            var options = columns[0].querySelectorAll('.s-cascader__option');
            for(var i=0; i<options.length; i++){{
                if(options[i].textContent.trim() === '{prov_name}'){{
                    options[i].click();
                    return;
                }}
            }}
        }})();
        """)
        time.sleep(0.3)

        # 获取第二列（城市）
        columns = get_cascader_columns(tab)
        if len(columns) < 2:
            print(f"  {prov_name} 无城市数据")
            all_data.append({"name": prov_name, "cities": []})
            continue

        cities = columns[1]
        print(f"  城市数: {len(cities)}")

        prov_data = {"name": prov_name, "cities": []}

        for ci, city in enumerate(cities):
            city_name = city['text']

            # 点击城市
            tab.run_js(f"""
            (function(){{
                var columns = document.querySelectorAll('.s-cascader__options');
                if(columns.length < 2) return;
                var options = columns[1].querySelectorAll('.s-cascader__option');
                for(var i=0; i<options.length; i++){{
                    if(options[i].textContent.trim() === '{city_name}'){{
                        options[i].click();
                        return;
                    }}
                }}
            }})();
            """)
            time.sleep(0.2)

            # 获取第三列（区）
            columns = get_cascader_columns(tab)
            districts = []
            if len(columns) >= 3:
                districts = [d['text'] for d in columns[2]]

            city_entry = {"name": city_name}
            if districts:
                city_entry["districts"] = districts

            prov_data["cities"].append(city_entry)

            if (ci + 1) % 5 == 0:
                print(f"    已处理 {ci+1}/{len(cities)} 城市")

        all_data.append(prov_data)
        print(f"  完成: {prov_name} ({len(prov_data['cities'])} 城市)")

    return all_data


def scrape_year_range(tab):
    """爬取出生年月的年份范围"""
    print("\n=== 爬取年份范围 ===")

    # 先关闭城市选择器（如果开着）
    tab.run_js("""
    (function(){
        var closeBtn = document.querySelector('.s-dialog[aria-label="请选择行政区"] .s-dialog__headerbtn');
        if(closeBtn) closeBtn.click();
    })();
    """)
    time.sleep(0.5)

    # 点击出生年月的日期选择器
    clicked = tab.run_js("""
    return (function(){
        var labels = document.querySelectorAll('span, div, label');
        for(var i=0; i<labels.length; i++){
            if(labels[i].textContent.trim() === '出生年月' && labels[i].children.length === 0){
                var row = labels[i].closest('.resume-item') || labels[i].parentElement.parentElement;
                if(row){
                    // 找到日期显示区域 (如 "1996-11")
                    var dateEl = row.querySelector('[class*=date], [class*=picker], [class*=select], input');
                    if(dateEl){
                        dateEl.click();
                        return 'clicked: ' + dateEl.className + ' text=' + dateEl.textContent.trim();
                    }
                    // 找包含数字的span
                    var spans = row.querySelectorAll('span, div');
                    for(var j=0; j<spans.length; j++){
                        if(spans[j].textContent.match(/\\d{4}/) && spans[j].children.length === 0){
                            spans[j].click();
                            return 'clicked date span: ' + spans[j].textContent.trim();
                        }
                    }
                }
                return 'found label, no date element';
            }
        }
        return 'label not found';
    })();
    """)
    print(f"Click result: {clicked}")
    time.sleep(1)

    # 获取年份选择器数据
    year_data = tab.run_js("""
    return (function(){
        // 查找日期选择器面板 - 可能是 s-date-picker 或类似组件
        var panels = document.querySelectorAll('[class*=picker-panel], [class*=date-panel], [class*=year-panel], [class*=date-picker]');
        var result = {panels: []};
        for(var i=0; i<panels.length; i++){
            var p = panels[i];
            if(p.offsetWidth > 0){
                result.panels.push({
                    class: p.className.substring(0, 150),
                    text: p.textContent.substring(0, 500),
                    childCount: p.children.length
                });
            }
        }
        // 查找所有可见的年份数字
        var years = [];
        var allEls = document.querySelectorAll('span, div, td, a, li, button');
        for(var i=0; i<allEls.length; i++){
            var t = allEls[i].textContent.trim();
            if(t.match(/^\\d{4}$/) && allEls[i].offsetWidth > 0 && allEls[i].children.length === 0){
                years.push({year: t, tag: allEls[i].tagName, class: allEls[i].className.substring(0, 60)});
            }
        }
        result.visibleYears = years;

        // 查找月份
        var months = [];
        for(var i=0; i<allEls.length; i++){
            var t = allEls[i].textContent.trim();
            if(t.match(/^\\d{1,2}月$/) && allEls[i].offsetWidth > 0 && allEls[i].children.length === 0){
                months.push(t);
            }
        }
        result.visibleMonths = months;

        return result;
    })();
    """)
    print(f"Year data: {json.dumps(year_data, ensure_ascii=False)[:800]}")
    return year_data


if __name__ == "__main__":
    page = create_browser()
    tab = page.latest_tab
    print(f"已连接: {tab.url}")

    # 1. 爬取城市三级数据
    city_data = scrape_all_cities(tab)
    if city_data:
        output_path = os.path.join(_DATA_DIR, "zhilian_cities_full.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(city_data, f, ensure_ascii=False, indent=2)
        print(f"\n城市数据已保存: {output_path}")
        total_cities = sum(len(p['cities']) for p in city_data)
        total_districts = sum(len(c.get('districts', [])) for p in city_data for c in p['cities'])
        print(f"统计: {len(city_data)} 省, {total_cities} 市, {total_districts} 区")

    # 2. 爬取年份范围
    year_data = scrape_year_range(tab)
    if year_data:
        with open(os.path.join(_DATA_DIR, "zhilian_year_debug.json"), "w", encoding="utf-8") as f:
            json.dump(year_data, f, ensure_ascii=False, indent=2)

    print("\n=== 全部完成 ===")
