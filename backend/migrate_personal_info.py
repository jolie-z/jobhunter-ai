import asyncio
import os
import sys

# Add the project root to sys.path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.config import settings
from app.core.feishu_client import feishu_client

def split_resume_content(markdown: str):
    """
    Split markdown into personal info and remaining resume content.
    Returns (personal_info, remaining_content)
    """
    if not markdown:
        return "", ""
        
    lines = markdown.split('\n')
    personal_info_lines = []
    remaining_lines = []
    
    in_personal_info = False
    found_personal_info = False
    
    for line in lines:
        stripped = line.strip()
        # Detect new header
        if stripped.startswith('# '):
            title = stripped[2:].strip()
            if title == '个人信息':
                in_personal_info = True
                found_personal_info = True
                personal_info_lines.append(line)
            else:
                in_personal_info = False
                remaining_lines.append(line)
        else:
            if in_personal_info:
                personal_info_lines.append(line)
            else:
                remaining_lines.append(line)
                
    if not found_personal_info:
        return "", markdown
        
    return "\n".join(personal_info_lines).strip(), "\n".join(remaining_lines).strip()

async def main():
    print("Starting migration...")
    resumes = await feishu_client.fetch_bitable_records(settings.FEISHU_TABLE_ID_RESUMES)
    print(f"Found {len(resumes)} resumes.")
    
    for resume in resumes:
        record_id = resume.get("record_id")
        fields = resume.get("fields", {})
        content = fields.get("简历内容", "")
        
        if not isinstance(content, str) and isinstance(content, list):
            if content:
                content = content[0].get("text", "")
            else:
                content = ""
                
        if not content:
            continue
            
        personal_info, remaining = split_resume_content(content)
        
        if personal_info:
            print(f"Updating record {record_id}...")
            
            success = await feishu_client.update_record(
                table_id=settings.FEISHU_TABLE_ID_RESUMES,
                record_id=record_id,
                fields={
                    "简历内容": remaining,
                    "个人信息": personal_info
                }
            )
            
            if success:
                print(f"Successfully migrated {record_id}")
            else:
                print(f"Failed to migrate {record_id}")
        else:
            print(f"Record {record_id} has no personal info block to migrate.")

if __name__ == "__main__":
    asyncio.run(main())
