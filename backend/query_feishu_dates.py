import asyncio
from app.core.feishu_client import feishu_client
from app.core.config import settings
from collections import Counter
from datetime import datetime

async def main():
    print(f"Fetching records from FEISHU_TABLE_ID_JOBS: {settings.FEISHU_TABLE_ID_JOBS}")
    records = await feishu_client.fetch_bitable_records(settings.FEISHU_TABLE_ID_JOBS)
    
    dates_counter = Counter()
    
    for r in records:
        fields = r.get("fields", {})
        # Depending on how it's stored, it might be a timestamp or a string
        scrape_time = fields.get("抓取时间", "")
        if scrape_time:
            # Assuming it's a timestamp in ms or seconds, or a date string
            # We'll print a few raw values first just to see
            if type(scrape_time) in (int, float):
                # convert to datetime
                try:
                    dt = datetime.fromtimestamp(scrape_time / 1000)
                    date_str = dt.strftime('%Y-%m-%d')
                    dates_counter[date_str] += 1
                except:
                    pass
            elif type(scrape_time) is str:
                # parse string
                try:
                    # just take first 10 chars "YYYY-MM-DD"
                    date_str = scrape_time[:10]
                    dates_counter[date_str] += 1
                except:
                    pass
            else:
                # unknown type
                print("Unknown type:", type(scrape_time), scrape_time)
                
    if not dates_counter:
        print("No valid 抓取时间 found in records.")
        return
        
    print("\nDates count:")
    for date_str, count in sorted(dates_counter.items()):
        print(f"{date_str}: {count} records")
        
    earliest_date = sorted(dates_counter.keys())[0]
    print(f"\nEarliest date recorded: {earliest_date}")

if __name__ == "__main__":
    asyncio.run(main())
