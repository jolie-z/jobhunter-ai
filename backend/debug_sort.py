import asyncio
from app.jobs.service import fetch_and_clean_all_jobs
import random

async def main():
    jobs = await fetch_and_clean_all_jobs()
    
    def _parse_fetch_time(job) -> float:
        ft = job.get("fetch_time", "")
        base = 0.0
        if ft:
            if ft.isdigit():
                val = float(ft)
                base = val if val > 1e11 else val * 1000
            else:
                try:
                    import dateutil.parser
                    base = dateutil.parser.parse(ft).timestamp() * 1000
                except Exception:
                    pass
        return base

    print("Total jobs:", len(jobs))
    if not jobs: return
    
    # Let's see top 10 jobs in currently sorted array
    print("\n--- TOP 10 JOBS (already sorted by fetch_and_clean_all_jobs) ---")
    for j in jobs[:10]:
        print(f"fetch_time={j.get('fetch_time')}, title={j.get('job_title')}, parsed={_parse_fetch_time(j)}")

    print("\n--- Let's find jobs with 06-22 ---")
    for j in jobs:
        if '06-22' in str(j.get('fetch_time', '')) or '06/22' in str(j.get('fetch_time', '')):
            print(f"fetch_time={j.get('fetch_time')}, title={j.get('job_title')}, parsed={_parse_fetch_time(j)}")
            
    print("\n--- Bottom 10 JOBS ---")
    for j in jobs[-10:]:
        print(f"fetch_time={j.get('fetch_time')}, title={j.get('job_title')}, parsed={_parse_fetch_time(j)}")

if __name__ == "__main__":
    asyncio.run(main())
