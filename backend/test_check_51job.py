from app.services.feishu_service import get_jobs_to_deliver
print("=== get_jobs_to_deliver (51job, 待投递) ===")
jobs = get_jobs_to_deliver(target_platform='51job', target_status='待投递')
print(f"found {len(jobs)} jobs")
for j in jobs:
    print(f"  [{j['company']}] {j['job_title']}")
    print(f"    URL: {j['job_url'][:80]}")
    print(f"    greeting: {'(有)' if j.get('greeting') else '(空)'}")
    print(f"    record_id: {j['record_id']}")
