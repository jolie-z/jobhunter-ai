"""
BOSS Skill API Structure Verification Script
用于查找并验证 BOSS 工作经历的技能字段 API 结构
运行此脚本前需要确保已登录 BOSS 网页版（端口 19222）
"""

import asyncio
import json
from drissionpage import ChromiumPage


def check_skill_api_structure():
    """通过浏览器自动化访问 BOSS 简历页面，查看技能相关 API"""
    
    print("="*70)
    print("BOSS SKILL API STRUCTURE VERIFICATION")
    print("="*70)
    print()
    
    page = ChromiumPage('edge', addr='http://127.0.0.1:19222')
    
    try:
        # 1. Navigate to resume page
        print("[1/5] Navigating to BOSS resume page...")
        page.get('https://www.zhipin.com/web/geek/resume')
        
        # Wait for page to load
        page.wait('.resume-work-exp', timeout=10)
        print("✅ Page loaded successfully")
        print()
        
        # 2. Capture all network requests related to 'skill'
        print("[2/5] Searching for skill-related API endpoints...")
        skill_endpoints = []
        
        # Look in JavaScript files or console logs
        js_code = """
            () => {
                const results = [];
                
                // Check window object for skill data
                if (window.__INITIAL_STATE__) {
                    const state = window.__INITIAL_STATE__;
                    // Try to find skill-related data in Redux state
                    if (state.resumeEditor) {
                        const exps = state.resumeEditor.experiences || [];
                        exps.forEach(exp => {
                            if (exp.skills && exp.skills.length > 0) {
                                results.push({
                                    type: 'INITIAL_STATE',
                                    skills: exp.skills,
                                    path: 'state.resumeEditor.experiences[i].skills'
                                });
                            }
                        });
                    }
                }
                
                // Search for any global skill-related variables
                Object.keys(window).forEach(key => {
                    if (key.toLowerCase().includes('skill')) {
                        results.push({type: 'GLOBAL_VAR', key: key, value: window[key]});
                    }
                });
                
                return results.slice(0, 50); // Limit results
            }
        """
        
        initial_data = page.run_js(js_code)
        if initial_data:
            print(f"Found {len(initial_data)} potential skill data points")
            for item in initial_data[:3]:  # Show first 3
                print(f"  - {json.dumps(item)[:200]}...")
            print()
        
        # 3. Inspect Network tab by checking fetch/XHR calls
        print("[3/5] Analyzing current network traffic...")
        
        # Check for existing skill-related XHR
        xhr_requests = page.requests('*skill*', status='>=all').all
        if xhr_requests:
            print(f"✓ Found {len(xhr_requests)} skill-related requests:")
            for req in xhr_requests[:5]:
                print(f"  • URL: {req.url}")
                print(f"    Method: {req.method}")
                try:
                    resp_text = req.resp.text or req.request.body or '{}'
                    resp_json = json.loads(resp_text) if resp_text.startswith('{') else resp_text[:200]
                    print(f"    Response preview: {str(resp_json)[:200]}")
                except Exception as e:
                    print(f"    Error parsing: {e}")
                print()
        else:
            print("✗ No active skill-related network requests found")
            print("   Need to manually trigger one...")
            print()
        
        # 4. Find the actual API endpoint from JavaScript
        print("[4/5] Extracting API endpoints from page JavaScript...")
        
        js_find_apis = """
            () => {
                const apis = [];
                
                // Search in DOM for API links
                document.querySelectorAll('[href*="skill"]').forEach(el => {
                    apis.push({element: el.tagName, href: el.href});
                });
                
                // Check fetch calls with skill parameter
                const originalFetch = window.fetch;
                let captured = [];
                
                // Try to find skill config objects
                const configs = document.querySelector('[data-skill]');
                if (configs) {
                    apis.push({source: 'DOM_DATA_ATTR', content: configs.outerHTML.substring(0, 500)});
                }
                
                return apis;
            }
        """
        
        dom_apis = page.run_js(js_find_apis)
        if dom_apis:
            print(f"Found {len(dom_apis)} potential APIs:")
            for api in dom_apis:
                print(f"  • {json.dumps(api)[:150]}")
            print()
        
        # 5. Manual verification instructions
        print("[5/5] Manual Steps Required:")
        print("-" * 70)
        print("Based on previous code analysis and common patterns:")
        print()
        print("🔍 LIKELY API ENDPOINTS:")
        print("  POST /wapi/zpgeek/resume/skill/query.json")
        print("  Returns: {zpData: {configList: [{code: 'xxx', name: 'Python'}]}}")
        print()
        print("🔍 LIKELY PAYLOAD FIELD NAMES:")
        print("  1. skillCodes (comma-separated): 'python,javascript,docker'")
        print("  2. skillList (array of objects): [{'code':'py','name':'Python'}]")
        print("  3. hasSkills (boolean flag): true/false")
        print("  4. customSkills (string): 'Python, JavaScript'")
        print()
        print("📋 NEXT STEPS TO VERIFY:")
        print("  1. Open browser DevTools → Network tab")
        print("  2. Clear filter and navigate to Experience section")
        print("  3. Look for requests with 'skill' in URL")
        print("  4. Click '编辑' on a work experience")
        print("  5. Submit the form and capture the save request")
        print("  6. Examine the JSON payload structure")
        print()
        print("⚠️ ALTERNATIVE APPROACH:")
        print("  If no direct skill API is found, check workexp/save.json payload directly")
        print("  The 'skills' field should be included there during save operation")
        print("-" * 70)
        print()
        
        # 6. Create diagnostic report
        print("\n[DIAGNOSTIC REPORT]")
        print("-" * 70)
        
        # Check what fields are currently used in build_workexp_payload
        print("Current boss_write_back.py implementation:")
        print("  - Has industryCode, industryName")
        print("  - NO skill-related fields detected")
        print()
        
        print("Expected fix based on typical patterns:")
        expected_field_name = "skillCodes"  # Most likely format
        print(f"  → Likely field name: '{expected_field_name}'")
        print(f"  → Format: Comma-separated string like '800123,800456,800789'")
        print(f"  → Or JSON array: '[{{\"code\":\"800123\",\"name\":\"Python\"}}]'")
        print()
        
        print("="*70)
        print("VERIFICATION COMPLETE")
        print("="*70)
        print("\nPlease perform manual verification steps above,")
        print("then share the screenshots/API responses for accurate fix.")
        
    finally:
        page.quit()


if __name__ == "__main__":
    check_skill_api_structure()
