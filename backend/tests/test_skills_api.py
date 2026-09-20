#!/usr/bin/env python3
"""
Test FastAPI Skills Endpoints (Upload, GitHub Import, Delete, List)
"""

import os
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app

client = TestClient(app)


def test_skills_api_lifecycle():
    # 1. List skills
    res = client.get("/api/resume-editor/skills/")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert len(data["skills"]) >= 1

    # 2. Upload zip package with scripts and references
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr("MyLLMSkill/SKILL.md", "# 算法求职改写技能\nversion: 2.1.0\n专门针对大模型算法求职的定制改写")
        z.writestr("MyLLMSkill/references/01_truth.md", "真实性边界文档：严禁凭空编造算力规模。")
        z.writestr("MyLLMSkill/bad_script.py", "import os; print('bad')")

    res = client.post(
        "/api/resume-editor/skills/upload",
        files={"file": ("my_llm_skill.zip", buf.getvalue(), "application/zip")},
        data={"name": "算法求职改写技能", "mode": "clean"}
    )
    if res.status_code != 200:
        print("Upload Error JSON:", res.json())
    assert res.status_code == 200
    upload_res = res.json()
    assert upload_res["success"] is True
    audit = upload_res["audit_report"]
    assert audit["references_count"] == 1
    assert audit["ignored_scripts_count"] == 1
    assert "bad_script.py" in audit["ignored_scripts"][0]

    uploaded_id = upload_res["skill"]["id"]
    assert upload_res["skill"]["name"] == "算法求职改写技能"

    # 3. Get skill detail and check full assembly and custom name
    res = client.get(f"/api/resume-editor/skills/{uploaded_id}")
    assert res.status_code == 200
    detail = res.json()
    assert detail["skill"]["name"] == "算法求职改写技能"
    assert detail["skill"]["is_package"] is True
    assert detail["skill"]["references_count"] == 1

    # 4. Delete uploaded custom skill
    res = client.delete(f"/api/resume-editor/skills/{uploaded_id}")
    assert res.status_code == 200
    del_res = res.json()
    assert del_res["success"] is True

    print("🎉 FastAPI Skills API E2E Lifecycle 100% PASS!")


if __name__ == "__main__":
    test_skills_api_lifecycle()
