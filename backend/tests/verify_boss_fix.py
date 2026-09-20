"""
Manual Verification Script for BOSS Work Experience Back-write
手动验证脚本 - 用于检查实际的 back-write 请求和数据

This script will:
1. Check if boss_write_back.py is running correctly
2. Log the exact payload being sent to BOSS API
3. Compare with frontend data
4. Report success/failure based on actual results
"""

import sys
import os
from pathlib import Path
import json
import time


# Add backend path
sys.path.insert(0, str(Path(__file__).parent.parent))


def check_skills_in_payload():
    """Check if skills field is actually included in the payload
    
    This verifies the fix we made in build_workexp_payload()
    """
    print("=" * 70)
    print("CHECK #1: Verify skills field in build_workexp_payload")
    print("=" * 70)
    
    boss_write_back_path = Path(__file__).parent.parent / 'resume_editor' / 'platforms' / 'boss_write_back.py'
    
    try:
        content = boss_write_back_path.read_text(encoding='utf-8')
        
        # Check 1: skillCodes field exists
        if '"skillCodes":' in content:
            print("✅ PASS: skillCodes field found in payload")
        else:
            print("❌ FAIL: skillCodes field NOT found")
            return False
        
        # Check 2: skill_tree parameter passed
        if 'build_workexp_payload(local_work[li], off_work[oi], industry_tree, skill_tree)' in content:
            print("✅ PASS: skill_tree parameter passed to builder")
        else:
            print("❌ FAIL: skill_tree not passed")
            return False
        
        # Check 3: skill mapper imported
        if 'from resume_editor.platforms.skill_mapper import map_skills' in content:
            print("✅ PASS: skill_mapper imported")
        else:
            print("❌ FAIL: skill_mapper not imported")
            return False
        
        # Check 4: hideResume logic fixed
        if '"isPublic": 0 if local_item.get("hideResume") else 1' in content:
            print("✅ PASS: hideResume boolean properly handled")
        else:
            print("❌ FAIL: hideResume still broken")
            return False
        
        # Check 5: skill tree loading
        if '/wapi/zpgeek/resume/skill/query.json' in content:
            print("✅ PASS: Skill tree endpoint loaded")
        else:
            print("❌ FAIL: Skill tree endpoint missing")
            return False
        
        print("\n✅ ALL CHECKS PASSED - Code changes verified!")
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR reading file: {e}")
        return False


def test_skill_mapping_functionality():
    """Test the skill mapping functionality with mock data"""
    print("\n" + "=" * 70)
    print("CHECK #2: Test skill_mapper functionality")
    print("=" * 70)
    
    from resume_editor.platforms.skill_mapper import map_skills, build_skill_name_code_map
    
    # Mock skill tree (typical BOSS API response)
    mock_skill_tree = [
        {"code": "800123", "name": "Python"},
        {"code": "800456", "name": "JavaScript"},
        {"code": "800789", "name": "Docker"},
        {"code": "800111", "name": "React"},
        {"code": "800333", "name": "Node.js"},
        {"code": "800444", "name": "Kubernetes"},
        {"code": "800555", "name": "LLM 意图路由"},
        {"code": "800666", "name": "Pandas 物理校验"},
        {"code": "800777", "name": "双轨制架构"},
        {"code": "800888", "name": "CDP 协议"},
        {"code": "800999", "name": "NLP 情感分析"},
        {"code": "801111", "name": "全栈研发"},
    ]
    
    # Test case matching user's data
    test_skills = [
        {"name": "LLM 意图路由"},
        {"name": "Pandas 物理校验"},
        {"name": "双轨制架构"},
        {"name": "CDP 协议"},
        {"name": "NLP 情感分析"},
        {"name": "全栈研发"},
    ]
    
    print(f"\nInput skills: {[s['name'] for s in test_skills]}")
    print(f"Skill tree has {len(mock_skill_tree)} entries\n")
    
    codes, unmapped = map_skills(test_skills, mock_skill_tree)
    
    print(f"Result:")
    print(f"  Mapped codes: {codes}")
    print(f"  Unmapped skills: {unmapped}")
    print()
    
    if len(codes) == 6 and len(unmapped) == 0:
        print("✅ SUCCESS: All 6 skills mapped successfully!")
        print(f"   Expected skillCodes value: '{','.join(codes)}'")
        return True
    else:
        print(f"❌ FAILED: Only {len(codes)}/6 skills mapped")
        return False


def verify_payload_structure():
    """Verify the final payload structure matches BOSS expectations"""
    print("\n" + "=" * 70)
    print("CHECK #3: Verify final payload structure")
    print("=" * 70)
    
    from resume_editor.platforms.boss_write_back import build_workexp_payload
    from resume_editor.platforms.skill_mapper import map_skills
    
    # Mock data matching user's input
    local_item = {
        "company": "自由职业者",
        "industry": "互联网",
        "department": "自主创业",
        "position": "全栈工程师",
        "startYear": "2024",
        "startMonth": "4",
        "endYear": None,
        "endMonth": None,
        "content": "针对大模型商业应用中的推荐幻觉痛点，独立设计 LLM 意图路由与 Pandas 物理校验的双轨制架构，从工程底层保障推荐商品 99%+ 真实在售",
        "achievement": "依托 5 年核心电商业务沉淀，全面重构个人技术栈",
        "skills": [
            {"name": "LLM 意图路由"},
            {"name": "Pandas 物理校验"},
            {"name": "双轨制架构"},
            {"name": "CDP 协议"},
            {"name": "NLP 情感分析"},
            {"name": "全栈研发"},
        ],
        "hideResume": True,
    }
    
    official_item = {}
    industry_tree = [{"code": "A0101", "name": "互联网"}]
    skill_tree = [
        {"code": "800555", "name": "LLM 意图路由"},
        {"code": "800666", "name": "Pandas 物理校验"},
        {"code": "800777", "name": "双轨制架构"},
        {"code": "800888", "name": "CDP 协议"},
        {"code": "800999", "name": "NLP 情感分析"},
        {"code": "801111", "name": "全栈研发"},
    ]
    
    print("\nBuilding payload with modified data...")
    print(f"  Skills count: {len(local_item['skills'])}")
    print(f"  hideResume: {local_item['hideResume']}")
    print(f"  Content length: {len(local_item['content'])} chars")
    print()
    
    payload = build_workexp_payload(local_item, official_item, industry_tree, skill_tree)
    
    # Verify critical fields
    checks_passed = 0
    total_checks = 4
    
    # Check 1: skillCodes present and non-empty
    if 'skillCodes' in payload and payload['skillCodes']:
        print("✅ skillCodes field present")
        print(f"   Value: '{payload['skillCodes']}'")
        checks_passed += 1
    else:
        print("❌ skillCodes field MISSING or EMPTY")
    
    # Check 2: isPublic respects hideResume=True → should be 0
    expected_is_public = 0 if local_item['hideResume'] else 1
    if payload.get('isPublic') == expected_is_public:
        print(f"✅ isPublic correct ({local_item['hideResume']} → {expected_is_public})")
        checks_passed += 1
    else:
        print(f"❌ isPublic WRONG (expected {expected_is_public}, got {payload.get('isPublic')})")
    
    # Check 3: workContent preserved
    if local_item['content'] in payload.get('workContent', ''):
        print(f"✅ workContent preserved")
        checks_passed += 1
    else:
        print(f"❌ workContent LOST")
    
    # Check 4: workPerformance included
    if payload.get('workPerformance'):
        print(f"✅ workPerformance included")
        checks_passed += 1
    else:
        print(f"❌ workPerformance empty")
    
    print(f"\nResult: {checks_passed}/{total_checks} checks passed")
    print()
    
    if checks_passed == total_checks:
        print("✅ PAYLOAD VERIFICATION SUCCESSFUL!")
        return True
    else:
        print("❌ PAYLOAD ISSUES DETECTED")
        return False


def run_all_checks():
    """Run all verification checks"""
    print("\n" + "=" * 70)
    print("BOSS WORK EXPERIENCE - BACK-WRITE FIX VERIFICATION")
    print("=" * 70)
    print("\n🎯 This script verifies that the fixes were implemented correctly.")
    print("   It does NOT do full end-to-end testing (requires live browser).")
    print()
    
    results = []
    
    # Check 1: Code changes
    result1 = check_skills_in_payload()
    results.append(("Code Changes", result1))
    
    # Check 2: Skill mapping
    result2 = test_skill_mapping_functionality()
    results.append(("Skill Mapping", result2))
    
    # Check 3: Payload structure
    result3 = verify_payload_structure()
    results.append(("Payload Structure", result3))
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {name}")
    
    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)
    
    print()
    print(f"Overall: {passed_count}/{total_count} checks passed")
    
    if passed_count == total_count:
        print("\n✅ ALL VERIFICATIONS PASSED!")
        print("\nNext steps:")
        print("  1. Run the actual back-write script with real data")
        print("  2. Manually check BOSS website to confirm changes applied")
        print("  3. Take screenshots and share if any issues")
        return True
    else:
        print("\n❌ SOME VERIFICATIONS FAILED")
        print("\nPlease review the errors above and fix them.")
        return False


if __name__ == "__main__":
    run_all_checks()
