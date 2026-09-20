"""
v12 - 调用已发现的全量API获取数据
"""
import os, sys, time, json

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_RESUME_EDITOR_DIR = os.path.dirname(_SCRIPT_DIR)
DATA_DIR = os.path.join(_RESUME_EDITOR_DIR, "data")

from DrissionPage import ChromiumPage, ChromiumOptions

co = ChromiumOptions()
co.set_address('127.0.0.1:19222')
page = ChromiumPage(co)
print("已连接浏览器")

results = {}

# ========== 1. 国家配置 ==========
print("\n[1] 获取国家配置...")
resp = page.run_js('''
    const xhr = new XMLHttpRequest();
    xhr.open('GET', '/wapi/zpgeek/overseastraitoptions/country/config/query.json?_=' + Date.now(), false);
    xhr.withCredentials = true;
    xhr.send();
    return xhr.responseText;
''')
try:
    data = json.loads(resp)
    print(f"  code: {data.get('code')}")
    zpData = data.get('zpData', {})
    print(f"  zpData keys: {list(zpData.keys()) if isinstance(zpData, dict) else type(zpData)}")

    with open(os.path.join(DATA_DIR, "boss_country_config.json"), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if isinstance(zpData, dict):
        for key, val in zpData.items():
            if isinstance(val, list):
                print(f"  {key}: {len(val)} 项")
                if len(val) > 0:
                    print(f"    首项: {json.dumps(val[0], ensure_ascii=False)[:200]}")
                    if len(val) > 1:
                        print(f"    次项: {json.dumps(val[1], ensure_ascii=False)[:200]}")
            elif isinstance(val, dict):
                print(f"  {key}: {json.dumps(val, ensure_ascii=False)[:300]}")
            else:
                print(f"  {key}: {val}")

    results['country'] = zpData
except Exception as e:
    print(f"  错误: {e}")
    print(f"  原始: {resp[:500]}")

# ========== 2. 语言配置 ==========
print("\n[2] 获取语言配置...")
resp = page.run_js('''
    const xhr = new XMLHttpRequest();
    xhr.open('GET', '/wapi/zpCommon/country/getLanguageConfig?_=' + Date.now(), false);
    xhr.withCredentials = true;
    xhr.send();
    return xhr.responseText;
''')
try:
    data = json.loads(resp)
    print(f"  code: {data.get('code')}")
    zpData = data.get('zpData', {})
    print(f"  zpData: {json.dumps(zpData, ensure_ascii=False)[:500]}")

    with open(os.path.join(DATA_DIR, "boss_language_config.json"), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if zpData:
        results['language'] = zpData
    else:
        print("  zpData为空，尝试其他参数...")
        # 可能需要POST或额外参数
        for params in ['?source=1', '?type=all', '?version=2']:
            resp2 = page.run_js(f'''
                const xhr = new XMLHttpRequest();
                xhr.open('GET', '/wapi/zpCommon/country/getLanguageConfig{params}&_=' + Date.now(), false);
                xhr.withCredentials = true;
                xhr.send();
                return xhr.responseText;
            ''')
            try:
                data2 = json.loads(resp2)
                zpData2 = data2.get('zpData', {})
                if zpData2:
                    print(f"  参数{params}: {json.dumps(zpData2, ensure_ascii=False)[:300]}")
            except:
                pass
except Exception as e:
    print(f"  错误: {e}")

# ========== 3. 时长配置 ==========
print("\n[3] 获取时长配置...")
resp = page.run_js('''
    const xhr = new XMLHttpRequest();
    xhr.open('GET', '/wapi/zpCommon/country/getDurationConfig?_=' + Date.now(), false);
    xhr.withCredentials = true;
    xhr.send();
    return xhr.responseText;
''')
try:
    data = json.loads(resp)
    print(f"  code: {data.get('code')}")
    zpData = data.get('zpData', {})

    with open(os.path.join(DATA_DIR, "boss_duration_config.json"), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if isinstance(zpData, dict):
        for key, val in zpData.items():
            if isinstance(val, list):
                print(f"  {key}: {len(val)} 项")
                for item in val:
                    print(f"    {json.dumps(item, ensure_ascii=False)}")
            else:
                print(f"  {key}: {val}")
        results['duration'] = zpData
except Exception as e:
    print(f"  错误: {e}")

# ========== 总结 ==========
print(f"\n========== 总结 ==========")
for key, val in results.items():
    if isinstance(val, dict):
        for subkey, subval in val.items():
            if isinstance(subval, list):
                print(f"  {key}.{subkey}: {len(subval)} 项")
            else:
                print(f"  {key}.{subkey}: {type(subval).__name__}")
    elif isinstance(val, list):
        print(f"  {key}: {len(val)} 项")

print("\n完成!")
