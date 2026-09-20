import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "51job_scraper"))
import importlib
m = importlib.import_module("51job_auto_delivery")

job_data = {
    "record_id": "recvhPx2LzoZze",
    "job_url": "https://jobs.51job.com/guangzhou/170518784.html?s=sou_sou_soulb&t=0_0&req=6b668a8138baba9f465596f9c9",
    "file_token": "",
    "pdf_name": "resume",
    "greeting": "",
    "image_items": [],
}
result = m.deliver_job(job_data)
print(f"\n===== RESULT: {'SUCCESS' if result else 'FAIL'} =====")
