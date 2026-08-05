import requests
import sqlite3
import os
import json
import time
from datetime import datetime, timezone

JP_DATACENTERS = ["Elemental", "Gaia", "Mana", "Meteor"]
VELOCITY_THRESHOLD = 50.0  # 1日平均50個以上の高回転アイテムのみをターゲット

def init_db(db_path="data/market_data.db"):
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS items_pool (
        scope TEXT,
        item_id INTEGER,
        item_name TEXT,
        added_at TEXT,
        last_velocity REAL,
        is_active INTEGER DEFAULT 1,
        PRIMARY KEY (scope, item_id)
    )
    """)
    
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
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON market_logs(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_scope_item ON market_logs(scope, item_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pool_active ON items_pool(scope, is_active)")
    
    conn.commit()
    return conn

def export_web_json(conn, output_path="docs/data.json"):
    os.makedirs("docs", exist_ok=True)
    cursor = conn.cursor()
    
    web_data_by_scope = {}
    
    for scope in JP_DATACENTERS:
        cursor.execute("""
        SELECT timestamp, scope, item_id, item_name, daily_sale_velocity,
               min_price, avg_price, min_price_nq, min_price_hq,
               units_for_sale, listings_count, last_upload_time
        FROM market_logs
        WHERE scope = ? 
          AND timestamp = (SELECT MAX(timestamp) FROM market_logs WHERE scope = ?)
          AND daily_sale_velocity >= ?
        ORDER BY daily_sale_velocity DESC
        """, (scope, scope, VELOCITY_THRESHOLD))
        
        rows = cursor.fetchall()
        items = []
        for r in rows:
            items.append({
                "timestamp": r[0],
                "scope": r[1],
                "item_id": r[2],
                "item_name": r[3],
                "velocity": r[4],
                "min_price": r[5],
                "avg_price": r[6],
                "min_price_nq": r[7],
                "min_price_hq": r[8],
                "units_for_sale": r[9],
                "listings_count": r[10],
                "last_upload_time": r[11]
            })
        web_data_by_scope[scope] = items

    last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    web_data = {
        "last_updated": last_updated,
        "datacenters": JP_DATACENTERS,
        "velocity_threshold": VELOCITY_THRESHOLD,
        "data": web_data_by_scope
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(web_data, f, ensure_ascii=False, indent=2)
        
    print(f"Exported multi-DC web JSON (Velocity >= {VELOCITY_THRESHOLD}) to {output_path}")

def process_dc_pipeline(scope_name: str, conn, now_str: str):
    headers = {"User-Agent": "FFXIV-Market-Tracker/1.0"}
    cursor = conn.cursor()
    
    # -----------------------------------------------------------------
    # Step 1: 最近更新されたアイテムIDを最大100件フル取得
    # -----------------------------------------------------------------
    recent_url = "https://universalis.app/api/v2/extra/stats/recently-updated"
    try:
        res = requests.get(recent_url, headers=headers, timeout=10)
        res.raise_for_status()
        recent_items = res.json().get('items', [])[:100] # 最大100件フル取得
    except Exception as e:
        print(f"[{scope_name}] Step 1 Error: {e}")
        recent_items = []

    # -----------------------------------------------------------------
    # Step 2: 既存プールのアクティブアイテム + 新規発見100件を統合
    # -----------------------------------------------------------------
    cursor.execute("SELECT item_id FROM items_pool WHERE scope = ? AND is_active = 1", (scope_name,))
    pooled_item_ids = [row[0] for row in cursor.fetchall()]
    
    target_ids = list(set(pooled_item_ids + recent_items))
    if not target_ids:
        print(f"[{scope_name}] No target items to fetch.")
        return

    # -----------------------------------------------------------------
    # Step 3: 対象アイテムを一括詳細取得 (10件チャンク + レート制限回避ウェイト)
    # -----------------------------------------------------------------
    items_data = {}
    chunk_size = 10
    for i in range(0, len(target_ids), chunk_size):
        chunk = target_ids[i:i + chunk_size]
        ids_str = ",".join(map(str, chunk))
        detail_url = f"https://universalis.app/api/v2/{scope_name}/{ids_str}?listings=1"
        
        try:
            d_res = requests.get(detail_url, headers=headers, timeout=10)
            if d_res.status_code == 200:
                items_data.update(d_res.json().get('items', {}))
        except Exception as e:
            print(f"[{scope_name}] Detail fetch error for chunk: {e}")
            
        # APIレート制限(25req/s)に余裕を持たせるためのウェイト(0.1秒)
        time.sleep(0.1)

    if not items_data:
        return

    # -----------------------------------------------------------------
    # Step 4: XIVAPIで日本語アイテム名の一括取得 (50件ずつ分割取得)
    # -----------------------------------------------------------------
    all_item_ids = [int(k) for k in items_data.keys()]
    name_map = {}
    
    for i in range(0, len(all_item_ids), 50):
        ids_chunk = all_item_ids[i:i + 50]
        top_ids_str = ",".join(str(x) for x in ids_chunk)
        xivapi_url = f"https://xivapi.com/Item?ids={top_ids_str}&columns=ID,Name_ja&language=ja"
        
        try:
            x_res = requests.get(xivapi_url, headers=headers, timeout=10)
            if x_res.status_code == 200:
                results = x_res.json().get("Results", [])
                for item in results:
                    if isinstance(item, dict) and "ID" in item:
                        name_map[item["ID"]] = item.get("Name_ja", "Unknown")
        except Exception as e:
            print(f"[{scope_name}] XIVAPI error: {e}")
        time.sleep(0.1)

    # -----------------------------------------------------------------
    # Step 5: 選別・登録・除外（クリーンアップ）＆ログ保存
    # -----------------------------------------------------------------
    high_velocity_count = 0
    
    for item_id_str, data in items_data.items():
        item_id = int(item_id_str)
        velocity = float(data.get("dailySaleVelocity") or data.get("regularSaleVelocity") or 0.0)
        item_name = name_map.get(item_id, f"Unknown ({item_id})")
        
        last_upload_ms = data.get("lastUploadTime")
        last_upload_str = ""
        if last_upload_ms:
            last_upload_dt = datetime.fromtimestamp(last_upload_ms / 1000, tz=timezone.utc)
            last_upload_str = last_upload_dt.strftime("%Y-%m-%d %H:%M:%S")

        min_price = data.get("minPrice", 0)
        avg_price = round(data.get("averagePrice", 0), 1)
        min_price_nq = data.get("minPriceNQ", 0)
        min_price_hq = data.get("minPriceHQ", 0)
        units_for_sale = data.get("unitsForSale", 0)
        listings_count = data.get("listingsCount", 0)

        if velocity >= VELOCITY_THRESHOLD:
            high_velocity_count += 1
            cursor.execute("""
            INSERT INTO items_pool (scope, item_id, item_name, added_at, last_velocity, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(scope, item_id) DO UPDATE SET
                last_velocity = excluded.last_velocity,
                is_active = 1
            """, (scope_name, item_id, item_name, now_str, velocity))

            cursor.execute("""
            INSERT INTO market_logs (
                timestamp, scope, item_id, item_name,
                daily_sale_velocity, min_price, avg_price,
                min_price_nq, min_price_hq, units_for_sale,
                listings_count, last_upload_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now_str, scope_name, item_id, item_name,
                velocity, min_price, avg_price,
                min_price_nq, min_price_hq, units_for_sale,
                listings_count, last_upload_str
            ))
        else:
            cursor.execute("""
            UPDATE items_pool 
            SET is_active = 0, last_velocity = ?
            WHERE scope = ? AND item_id = ?
            """, (velocity, scope_name, item_id))

    print(f"[{scope_name}] Processed {len(items_data)} items -> High Velocity (>= {VELOCITY_THRESHOLD}/day): {high_velocity_count} items.")

def fetch_and_save_all():
    db_path = "data/market_data.db"
    conn = init_db(db_path)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for scope in JP_DATACENTERS:
        print(f"--- Processing DC: {scope} (100-item scan) ---")
        process_dc_pipeline(scope, conn, now_str)

    conn.commit()
    
    export_web_json(conn, "docs/data.json")
    
    conn.close()
    print(f"All 4 JP Datacenters pipeline completed (100-item full scan, Threshold >= {VELOCITY_THRESHOLD})!")

if __name__ == "__main__":
    fetch_and_save_all()
