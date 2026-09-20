#!/usr/bin/env python3
"""
BOSS Work Experience - End-to-End Integration Test (MANUAL EXECUTION)

This script helps verify that the back-write fix actually works on real BOSS website.
It requires a browser running with CDP debugging enabled at port 19222.
"""

from DrissionPage import ChromiumPage


def main():
    print("=" * 70)
    print("🔍 BOSS WORK EXPERIENCE - END-TO-END INTEGRATION TEST")
    print("=" * 70)
    print()
    
    # Step 1: Connect to browser
    print("[Step 1/6] Connecting to browser at port 19222...")
    try:
        page = ChromiumPage('http://127.0.0.1:19222')
        print("✅ Browser connected successfully!")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        print()
        print("Please start Edge with CDP:")
        print("  cd /Applications/Edge.app/Contents/MacOS/")
        print("  ./Google\\ Edge --remote-debugging-port=19222")
        exit(1)
    
    try:
        # Step 2: Load BOSS resume page
        print("\n[Step 2/6] Loading BOSS resume page...")
        page.get('https://www.zhipin.com/web/geek/resume')
        page.wait('.resume-work-exp', timeout=10)
        print("✅ Resume page loaded!")
        
        # Step 3: Check work experiences
        print("\n[Step 3/6] Checking current state...")
        work_items = page.eles('.resume-work-exp')
        print(f"📊 Found {len(work_items)} work experiences")
        
        if len(work_items) == 0:
            print("⚠️  No work experiences found")
            exit(1)
        
        first_item = work_items[0]
        company_name = first_item.text
        print(f"🏢 First experience: {company_name}")
        
        # Step 4: Save before screenshot
        page.save_screenshot('/tmp/boss_integration_before.png')
        print("📸 Before screenshot: /tmp/boss_integration_before.png")
        
        # Step 5: Summary
        print("\n" + "=" * 70)
        print("✅ TEST ENVIRONMENT READY")
        print("=" * 70)
        print()
        print("Next steps for manual verification:")
        print()
        print("1️⃣  Edit work experience in frontend")
        print("   • http://localhost:3000/resume-editor")
        print("   • Click edit on '自由职业者'")
        print("   • Add 6 skills: LLM 意图路由，Pandas 物理校验，双轨制架构，CDP 协议，NLP 情感分析，全栈研发")
        print("   • Check: 对该家公司隐藏我的简历 ✓")
        print("   • Save snapshot")
        print()
        print("2️⃣  Run back-write script")
        print("   cd backend")
        print("   python resume_editor/platforms/boss_write_back.py --paths work_experience --json ../local_fields.json")
        print()
        print("3️⃣  Come back here and I will verify on BOSS website")
        print()
        print("💡 Browser is now open at https://www.zhipin.com/web/geek/resume")
        print()
        
        # Close immediately after summary
        page.quit()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            page.quit()
        except:
            pass


if __name__ == "__main__":
    main()
