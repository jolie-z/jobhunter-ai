import asyncio
from app.strategy.service import get_all_strategy_configs

async def main():
    data = await get_all_strategy_configs()
    for resume in data["resumes"]:
        if resume.get("avatar_url"):
            print(f"Resume: {resume['version_name']}, Avatar URL: {resume['avatar_url']}")
        else:
            print(f"Resume: {resume['version_name']}, NO AVATAR URL")

if __name__ == "__main__":
    asyncio.run(main())
