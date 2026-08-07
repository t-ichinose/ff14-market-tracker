"""30-minute automatic data collection loop for FFXIV Market Tracker."""
import time
import subprocess
import sys
from datetime import datetime, timezone

INTERVAL_SECONDS = 30 * 60  # 30分 (1800秒)

print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] Started 30-minute auto data collection scheduler.")

while True:
    try:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n==========================================")
        print(f"[{now_str}] Starting scheduled 30-minute fetch & update (entriesToReturn=500)...")
        print(f"==========================================")
        
        # main.py の全32ワールドデータ取得・重複排除蓄積・JSON出力を実行
        res = subprocess.run([sys.executable, "main.py"], capture_output=True, text=True)
        if res.returncode == 0:
            print("Successfully completed data fetch, deduplication insert, and web JSON export.")
        else:
            print(f"Main execution output error:\n{res.stderr}")
            
        finish_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{finish_str}] Scheduled cycle complete. Next cycle in 30 minutes.")
    except Exception as e:
        print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] Error in scheduled loop: {e}")
    
    # 30分間 (1800秒) 待機
    time.sleep(INTERVAL_SECONDS)
