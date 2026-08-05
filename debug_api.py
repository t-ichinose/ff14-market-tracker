import requests
import json

def debug_apis():
    # 1. Universalis Recently Updated
    recent_url = "https://universalis.app/api/v2/extra/stats/recently-updated"
    res = requests.get(recent_url, timeout=10)
    recent_items = res.json().get('items', [])[:5]
    print("Recently updated items:", recent_items)

    if recent_items:
        ids_str = ",".join(map(str, recent_items))
        # まずパラメータなしで取得してみる
        detail_url = f"https://universalis.app/api/v2/Chocobo/{ids_str}"
        detail_res = requests.get(detail_url, timeout=10)
        items_data = detail_res.json().get('items', {})
        
        for item_id, item_info in list(items_data.items())[:2]:
            print(f"\n--- Universalis Item {item_id} ---")
            print("dailySaleVelocity:", item_info.get("dailySaleVelocity"))
            print("minPrice:", item_info.get("minPrice"))
            print("averagePrice:", item_info.get("averagePrice"))

        # 2. XIVAPI 日本語名取得テスト
        top_ids_str = ",".join(str(x) for x in recent_items)
        xivapi_url = f"https://xivapi.com/Item?ids={top_ids_str}&columns=ID,Name_ja&language=ja"
        xiv_res = requests.get(xivapi_url, timeout=10)
        print("\n--- XIVAPI Response Status ---", xiv_res.status_code)
        try:
            xiv_data = xiv_res.json()
            print("XIVAPI Keys:", list(xiv_data.keys()) if isinstance(xiv_data, dict) else type(xiv_data))
            if isinstance(xiv_data, dict):
                results = xiv_data.get("Results", [])
                print("Results type:", type(results))
                if isinstance(results, list):
                    for r in results:
                        print("Item:", r)
        except Exception as e:
            print("XIVAPI Error:", e)

if __name__ == "__main__":
    debug_apis()
