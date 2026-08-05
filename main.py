import requests
import csv
import os
from datetime import datetime, timezone

def fetch_and_save():
    scope_name = "Mana"
    recent_url = "https://universalis.app/api/v2/extra/stats/recently-updated"
    
    headers = {"User-Agent": "FFXIV-Market-Tracker/1.0"}
    
    # 1. 直近更新アイテムIDを取得（20件）
    try:
        res = requests.get(recent_url, headers=headers, timeout=10)
        res.raise_for_status()
        recent_items = res.json().get('items', [])[:20]
    except Exception as e:
        print(f"Error fetching recently updated: {e}")
        return

    if not recent_items:
        return

    # 2. 10件ずつ小分けで詳細取得
    items_data = {}
    chunk_size = 10
    for i in range(0, len(recent_items), chunk_size):
        chunk = recent_items[i:i + chunk_size]
        ids_str = ",".join(map(str, chunk))
        detail_url = f"https://universalis.app/api/v2/{scope_name}/{ids_str}?listings=1&entries=5"
        
        try:
            d_res = requests.get(detail_url, headers=headers, timeout=10)
            if d_res.status_code == 200:
                items_data.update(d_res.json().get('items', {}))
        except Exception as e:
            print(f"Error fetching detail chunk: {e}")

    # 3. 販売速度順にソート（上位10件）
    parsed_list = []
    for item_id, data in items_data.items():
        velocity = data.get("dailySaleVelocity") or 0.0
        
        # UNIXタイムスタンプ(ミリ秒)を日時に変換
        last_upload_ms = data.get("lastUploadTime")
        last_upload_str = ""
        if last_upload_ms:
            last_upload_dt = datetime.fromtimestamp(last_upload_ms / 1000, tz=timezone.utc)
            last_upload_str = last_upload_dt.strftime("%Y-%m-%d %H:%M:%S")

        parsed_list.append({
            "item_id": int(item_id),
            "velocity": float(velocity),
            "min_price": data.get("minPrice", 0),
            "avg_price": round(data.get("averagePrice", 0), 1),
            "min_price_nq": data.get("minPriceNQ", 0),
            "min_price_hq": data.get("minPriceHQ", 0),
            "units_for_sale": data.get("unitsForSale", 0),
            "listings_count": data.get("listingsCount", 0),
            "last_upload_time": last_upload_str
        })
    
    parsed_list.sort(key=lambda x: x["velocity"], reverse=True)
    top_items = parsed_list[:10]

    if not top_items:
        return

    # 4. XIVAPIで日本語名取得
    top_ids_str = ",".join(str(x["item_id"]) for x in top_items)
    xivapi_url = f"https://xivapi.com/Item?ids={top_ids_str}&columns=ID,Name_ja&language=ja"
    
    name_map = {}
    try:
        x_res = requests.get(xivapi_url, headers=headers, timeout=10)
        if x_res.status_code == 200:
            results = x_res.json().get("Results", [])
            for item in results:
                if isinstance(item, dict) and "ID" in item:
                    name_map[item["ID"]] = item.get("Name_ja", "Unknown")
    except Exception as e:
        print(f"Error fetching XIVAPI names: {e}")

    # 5. CSVファイルに追記保存
    os.makedirs("data", exist_ok=True)
    csv_path = "data/market_log.csv"
    file_exists = os.path.exists(csv_path)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    headers_row = [
        "日時", "スコープ", "アイテムID", "アイテム名", 
        "1日平均販売数(個/日)", "最安値(Gil)", "平均価格(Gil)", 
        "NQ最安値(Gil)", "HQ最安値(Gil)", "総出品数量", "出品件数", "データ更新日時(UTC)"
    ]

    with open(csv_path, mode="a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(headers_row)
        
        for item in top_items:
            i_id = item["item_id"]
            name = name_map.get(i_id, f"Unknown ({i_id})")
            writer.writerow([
                now_str, scope_name, i_id, name, 
                f"{item['velocity']:.1f}", item["min_price"], item["avg_price"],
                item["min_price_nq"], item["min_price_hq"], item["units_for_sale"],
                item["listings_count"], item["last_upload_time"]
            ])

    print("Successfully saved rich data to CSV!")

if __name__ == "__main__":
    fetch_and_save()
