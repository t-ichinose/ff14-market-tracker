import requests
import sqlite3
import os
from datetime import datetime, timezone

def init_db(db_path="data/market_data.db"):
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # テーブル作成
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS market_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        scope TEXT,
        item_id INTEGER,
        item_name TEXT,
        daily_sale_velocity REAL,
        min_price INTEGER,
        avg_price REAL,
        min_price_nq INTEGER,
        min_price_hq INTEGER,
        units_for_sale INTEGER,
        listings_count INTEGER,
        last_upload_time TEXT
    )
    """)
    
    # 高速検索用インデックス
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON market_logs(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_item_id ON market_logs(item_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_velocity ON market_logs(daily_sale_velocity)")
    
    conn.commit()
    return conn

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

    # 5. SQLiteデータベースに保存
    db_path = "data/market_data.db"
    conn = init_db(db_path)
    cursor = conn.cursor()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for item in top_items:
        i_id = item["item_id"]
        name = name_map.get(i_id, f"Unknown ({i_id})")
        
        cursor.execute("""
        INSERT INTO market_logs (
            timestamp, scope, item_id, item_name,
            daily_sale_velocity, min_price, avg_price,
            min_price_nq, min_price_hq, units_for_sale,
            listings_count, last_upload_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now_str, scope_name, i_id, name,
            item["velocity"], item["min_price"], item["avg_price"],
            item["min_price_nq"], item["min_price_hq"], item["units_for_sale"],
            item["listings_count"], item["last_upload_time"]
        ))

    conn.commit()
    conn.close()

    print("Successfully saved data to SQLite Database (data/market_data.db)!")

if __name__ == "__main__":
    fetch_and_save()
