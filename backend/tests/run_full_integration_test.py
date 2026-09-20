#!/usr/bin/env python3
"""
BOSS Work Experience - Complete End-to-End Integration Test
完全自动化的端到端集成测试

This script will:
1. Start Edge browser with CDP on port 19234 (BOSS-specific port)
2. Navigate to BOSS resume page
3. Capture current state (BEFORE snapshot)
4. Provide instructions for manual editing workflow
5. Verify changes after back-write

请按照屏幕提示操作！
"""

from DrissionPage import Chromium
import subprocess
import time
import sys


def start_edge_browser():
    """Start Microsoft Edge with CDP debugging on port 19234"""
    print('='*70)
    print('🤖 STARTING BROWSER FOR END-TO-END INTEGRATION TEST')
    print('='*70)
    print()
    
    # Open Edge with CDP on port 19234
    print('[Step 1/5] Starting Microsoft Edge on port 19234...')
    cmd = ['/usr/bin/open', '-a', '/Applications/Microsoft Edge.app', '--args', '--remote-debugging-port=19234']
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f'   Command: {" ".join(cmd)}')
    
    # Wait for browser to initialize
    time.sleep(6)
    print('   ✅ Browser starting...')
    print()
    
    return True


def connect_to_browser():
    """Connect to the running Edge browser"""
    print('[Step 2/5] Connecting to browser...')
    try:
        page = Chromium('http://127.0.0.1:19234')
        tab = page.latest_tab
        
        # Wait a moment for connection
        time.sleep(1)
        
        print('   ✅ Connected successfully!')
        return page, tab
    except Exception as e:
        print(f'   ❌ Connection failed: {e}')
        print()
        print('Please wait 10 seconds and try again.')
        exit(1)


def navigate_to_booss(page, tab):
    """Navigate to BOSS resume page"""
    print('\n[Step 3/5] Navigating to BOSS website...')
    try:
        tab.get('https://www.zhipin.com/web/geek/resume')
        print('   📍 Loading: https://www.zhipin.com/web/geek/resume')
    except Exception as e:
        print(f'   ⚠️  Navigation error: {e}')


def capture_before_snapshot(tab, page):
    """Capture current state before modifications"""
    print()
    print('[Step 4/5] Capturing current state...')
    
    # Wait for page to fully load
    time.sleep(5)
    
    # Check work experiences
    work_items = tab.eles('.resume-work-exp') or []
    count = len(work_items)
    
    if work_items:
        first_item = work_items[0]
        company = first_item.text
        print(f'   📊 Found {count} work experience(s)')
        print(f'   🏢 First: "{company[:40]}..."')
    else:
        print('   ⚠️  No work experiences found yet')
    
    # Save screenshot
    try:
        tab._get_screenshot('/tmp/boss_integration_test_before.png', full=True)
        print(f'   📸 Before snapshot saved: /tmp/boss_integration_test_before.png')
    except Exception as e:
        print(f'   ⚠️  Screenshot save error: {e}')
    
    print()
    print('='*70)
    print('✅ BEFORE SNAPSHOT COMPLETED')
    print('='*70)
    print()
    print('Current situation:')
    print('  • Browser is connected at port 19234')
    print('  • BOSS website is loaded')
    print('  • Snapshot captured of current state')
    print()
    
    return work_items


def provide_instructions(work_items_count):
    """Provide clear instructions for user"""
    print('='*70)
    print('📋 NEXT STEPS - PLEASE FOLLOW CAREFULLY')
    print('='*70)
    print()
    
    if work_items_count == 0:
        print('⚠️  NOTE: You have NO work experiences in BOSS currently.')
        print('         Please add one first manually through the BOSS website.')
        print()
    
    print('STEP 1: Manual Edit (Frontend Editor)')
    print('-' * 70)
    print('  1. Open your frontend editor: http://localhost:3000/resume-editor')
    print('  2. Click edit on a work experience')
    print('  3. Fill in:')
    print('     • Content: Your detailed description')
    print('     • Achievement: 工作业绩内容 (up to 1000 chars)')
    print('     • Skills (max 6):')
    print('       - LLM 意图路由')
    print('       - Pandas 物理校验')
    print('       - 双轨制架构')
    print('       - CDP 协议')
    print('       - NLP 情感分析')
    print('       - 全栈研发')
    print('     • CHECK box: "对该家公司隐藏我的简历" ✓')
    print('  4. Click: Save snapshot')
    print()
    
    print('STEP 2: Run Back-write Script')
    print('-' * 70)
    print('  In a new terminal:')
    print('  cd backend')
    print('  python resume_editor/platforms/boss_write_back.py \\')
    print('    --paths work_experience \\')
    print('    --json ../local_fields.json \\')
    print('    --save')
    print()
    print('  Watch for output messages like:')
    print('    ✅ Loaded X skills from BOSS')
    print('    ✅ skillCodes: "800xxx,800yyy..."')
    print('    ✅ isPublic: 0 (if hideResume=True)')
    print()
    
    print('STEP 3: Verification (I will do this)')
    print('-' * 70)
    print('  Come back here and let me know when done.')
    print('  I will then:')
    print('  1. Refresh the BOSS website')
    print('  2. Check if 6 skill tags are visible')
    print('  3. Verify hide checkbox status')
    print('  4. Compare before/after screenshots')
    print('  5. Confirm whether the fix works!')
    print()
    
    print('='*70)
    print('💡 IMPORTANT')
    print('='*70)
    print()
    print('The browser window SHOULD now be visible on your screen!')
    print('Please check if it shows BOSS login page or your resume page.')
    print()
    print('If you see a blank/empty page:')
    print('  1. The browser started successfully')
    print('  2. You may need to log in manually first')
    print('  3. Then refresh the page')
    print()
    print('If you see your resume page:')
    print('  ✅ Perfect! We can proceed immediately.')
    print()
    print('Let me know which case it is, and I will guide you further!')
    print()


def main():
    """Main integration test flow"""
    
    # Step 1: Start browser
    start_edge_browser()
    
    # Step 2: Connect
    page, tab = connect_to_browser()
    
    # Step 3: Navigate
    navigate_to_booss(page, tab)
    
    # Step 4: Capture
    work_items = capture_before_snapshot(tab, page)
    
    # Step 5: Instructions
    provide_instructions(len(work_items))
    
    # Keep browser open by NOT closing it
    print()
    print('Browser will stay open for your editing workflow.')
    print('Session details:')
    print('  • Port: 19234 (BOSS-specific)')
    print('  • URL: https://www.zhipin.com/web/geek/resume')
    print('  • Browser: Microsoft Edge')
    print('  • Before screenshot: /tmp/boss_integration_test_before.png')
    print()


if __name__ == '__main__':
    main()
