import requests
import sqlite3
import os
import json
import time
import re
from datetime import datetime, timezone

JP_DATACENTERS = ["Elemental", "Gaia", "Mana", "Meteor"]
VELOCITY_THRESHOLD = 50.0  # 1日平均50個以上の高回転品のみ

def init_db(db_path="data/market_data.db"):
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS items_pool (
        scope TEXT,
        item_key TEXT,
        item_id INTEGER,
        item_name TEXT,
        quality TEXT,
        added_at TEXT,
        last_velocity REAL,
        is_active INTEGER DEFAULT 1,
        PRIMARY KEY (scope, item_key)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS market_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        scope TEXT,
        item_key TEXT,
        item_id INTEGER,
        item_name TEXT,
        quality TEXT,
        daily_sale_velocity REAL,
        min_price INTEGER,
        avg_price REAL,
        units_for_sale INTEGER,
        listings_count INTEGER,
        last_upload_time TEXT
    )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON market_logs(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_scope_key ON market_logs(scope, item_key)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pool_active ON items_pool(scope, is_active)")
    
    conn.commit()
    return conn

def clean_name(raw_name):
    return re.sub(r'\s*\[(NQ|HQ)\]\s*$', '', raw_name).strip()

def export_web_json(conn, output_path="docs/data.json"):
    os.makedirs("docs", exist_ok=True)
    cursor = conn.cursor()
    
    # 1. 各DCの最新ログを取得
    raw_data_by_scope = {}
    item_cross_dc = {}  # 全DCでのクロス分析用キー辞書
    
    for scope in JP_DATACENTERS:
        cursor.execute("""
        SELECT timestamp, scope, item_key, item_id, item_name, quality,
               daily_sale_velocity, min_price, avg_price,
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
            item_obj = {
                "timestamp": r[0],
                "scope": r[1],
                "item_key": r[2],
                "item_id": r[3],
                "item_name": clean_name(r[4]),
                "quality": r[5],
                "velocity": r[6],
                "min_price": r[7],
                "avg_price": r[8],
                "units_for_sale": r[9],
                "listings_count": r[10],
                "last_upload_time": r[11]
            }
            items.append(item_obj)
            
            # クロスDC用に記録
            ikey = r[2]
            if ikey not in item_cross_dc:
                item_cross_dc[ikey] = []
            item_cross_dc[ikey].append({
                "scope": r[1],
                "min_price": r[7],
                "velocity": r[6]
            })
            
        raw_data_by_scope[scope] = items

    # 2. 全DC間での価格比較（最安仕入れDC ➔ 最高販売DC 利益計算）
    cross_analytics = {}
    for ikey, dc_list in item_cross_dc.items():
        valid_prices = [x for x in dc_list if x["min_price"] > 0]
        if len(valid_prices) >= 2:
            sorted_by_price = sorted(valid_prices, key=lambda x: x["min_price"])
            cheapest = sorted_by_price[0]
            highest = sorted_by_price[-1]
            
            cheap_price = cheapest["min_price"]
            high_price = highest["min_price"]
            
            # 手数料5%考慮の想定純利益
            profit_gil = int(high_price * 0.95 - cheap_price)
            profit_rate = round((profit_gil / cheap_price) * 100, 1) if cheap_price > 0 else 0.0
            
            if profit_gil > 0 and profit_rate >= 10.0: # 利益10%以上
                cross_analytics[ikey] = {
                    "cheap_scope": cheapest["scope"],
                    "cheap_price": cheap_price,
                    "high_scope": highest["scope"],
                    "high_price": high_price,
                    "profit_gil": profit_gil,
                    "profit_rate": profit_rate
                }

    # 3. アイテムデータに計算指標を添付
    final_data_by_scope = {}
    for scope, items in raw_data_by_scope.items():
        enriched_items = []
        for item in items:
            ikey = item["item_key"]
            vel = item["velocity"]
            min_p = item["min_price"]
            avg_p = item["avg_price"]
            units = item["units_for_sale"]
            
            # 在庫消化日数 = 在庫数 / 1日販売数
            days_to_clear = round(units / vel, 1) if vel > 0 else 999.0
            
            # 割安率 = (平均価格 - 最安値) / 平均価格
            discount_rate = round(((avg_p - min_p) / avg_p) * 100, 1) if avg_p > min_p else 0.0
            
            # DC間利益データ
            cross_info = cross_analytics.get(ikey)
            
            item["days_to_clear"] = days_to_clear
            item["discount_rate"] = discount_rate
            item["cross_info"] = cross_info
            
            enriched_items.append(item)
            
        final_data_by_scope[scope] = enriched_items

    last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    web_data = {
        "last_updated": last_updated,
        "datacenters": JP_DATACENTERS,
        "velocity_threshold": VELOCITY_THRESHOLD,
        "data": final_data_by_scope
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(web_data, f, ensure_ascii=False, indent=2)
        
    print(f"Exported enriched web JSON to {output_path}")

def process_dc_pipeline(scope_name: str, conn, now_str: str):
    headers = {"User-Agent": "FFXIV-Market-Tracker/1.0"}
    cursor = conn.cursor()
    
    recent_url = "https://universalis.app/api/v2/extra/stats/recently-updated"
    try:
        res = requests.get(recent_url, headers=headers, timeout=10)
        res.raise_for_status()
        recent_items = res.json().get('items', [])[:100]
    except Exception as e:
        print(f"[{scope_name}] Step 1 Error: {e}")
        recent_items = []

    cursor.execute("SELECT item_id FROM items_pool WHERE scope = ? AND is_active = 1", (scope_name,))
    pooled_item_ids = [row[0] for row in cursor.fetchall()]
    
    target_ids = list(set(pooled_item_ids + recent_items))
    if not target_ids:
        return

    items_data = {}
    chunk_size = 10
    for i in range(0, len(target_ids), chunk_size):
        chunk = target_ids[i:i + chunk_size]
        ids_str = ",".join(map(str, chunk))
        detail_url = f"https://universalis.app/api/v2/{scope_name}/{ids_str}?listings=1"
        
        try:
            d_res = requests.get(detail_url, headers=headers, timeout=15)
            if d_res.status_code == 200:
                items_data.update(d_res.json().get('items', {}))
        except Exception as e:
            print(f"[{scope_name}] Detail fetch error: {e}")
            
        time.sleep(0.1)

    if not items_data:
        return

    all_item_ids = [int(k) for k in items_data.keys()]
    name_map = {}
    for i in range(0, len(all_item_ids), 50):
        ids_chunk = all_item_ids[i:i + 50]
        top_ids_str = ",".join(str(x) for x in ids_chunk)
        xivapi_url = f"https://xivapi.com/Item?ids={top_ids_str}&columns=ID,Name_ja,CanBeHq&language=ja"
        
        try:
            x_res = requests.get(xivapi_url, headers=headers, timeout=10)
            if x_res.status_code == 200:
                results = x_res.json().get("Results", [])
                for item in results:
                    if isinstance(item, dict) and "ID" in item:
                        name_map[item["ID"]] = {
                            "name": clean_name(item.get("Name_ja", "Unknown")),
                            "can_be_hq": bool(item.get("CanBeHq", 0))
                        }
        except Exception as e:
            print(f"[{scope_name}] XIVAPI error: {e}")
        time.sleep(0.1)

    high_velocity_count = 0

    for item_id_str, data in items_data.items():
        item_id = int(item_id_str)
        item_meta = name_map.get(item_id, {"name": f"Unknown ({item_id})", "can_be_hq": False})
        pure_name = item_meta["name"]
        can_be_hq = item_meta["can_be_hq"]
        
        last_upload_ms = data.get("lastUploadTime")
        last_upload_str = ""
        if last_upload_ms:
            last_upload_dt = datetime.fromtimestamp(last_upload_ms / 1000, tz=timezone.utc)
            last_upload_str = last_upload_dt.strftime("%Y-%m-%d %H:%M:%S")

        avg_price = round(data.get("averagePrice", 0), 1)
        units_for_sale = data.get("unitsForSale", 0)
        listings_count = data.get("listingsCount", 0)

        nq_vel = float(data.get("nqSaleVelocity") or 0.0)
        hq_vel = float(data.get("hqSaleVelocity") or 0.0)
        total_vel = float(data.get("dailySaleVelocity") or data.get("regularSaleVelocity") or 0.0)
        
        nq_min = data.get("minPriceNQ") or data.get("minPrice", 0)
        hq_min = data.get("minPriceHQ") or 0

        if not can_be_hq:
            qualities = [("NONE", pure_name, total_vel, nq_min)]
        else:
            qualities = [
                ("NQ", f"{pure_name} [NQ]", nq_vel, nq_min),
                ("HQ", f"{pure_name} [HQ]", hq_vel, hq_min)
            ]

        for q_type, item_display_name, vel, price in qualities:
            item_key = f"{item_id}_{q_type}"

            if vel >= VELOCITY_THRESHOLD:
                high_velocity_count += 1
                cursor.execute("""
                INSERT INTO items_pool (scope, item_key, item_id, item_name, quality, added_at, last_velocity, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(scope, item_key) DO UPDATE SET
                    item_name = excluded.item_name,
                    quality = excluded.quality,
                    last_velocity = excluded.last_velocity,
                    is_active = 1
                """, (scope_name, item_key, item_id, item_display_name, q_type, now_str, vel))

                cursor.execute("""
                INSERT INTO market_logs (
                    timestamp, scope, item_key, item_id, item_name, quality,
                    daily_sale_velocity, min_price, avg_price,
                    units_for_sale, listings_count, last_upload_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    now_str, scope_name, item_key, item_id, item_display_name, q_type,
                    vel, price, avg_price, units_for_sale, listings_count, last_upload_str
                ))
            else:
                cursor.execute("""
                UPDATE items_pool 
                SET is_active = 0, last_velocity = ?
                WHERE scope = ? AND item_key = ?
                """, (vel, scope_name, item_key))

    print(f"[{scope_name}] Processed -> High Velocity Cards (>= {VELOCITY_THRESHOLD}/day): {high_velocity_count} cards.")

def fetch_and_save_all():
    db_path = "data/market_data.db"
    conn = init_db(db_path)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for scope in JP_DATACENTERS:
        print(f"--- Processing DC: {scope} (Enriched Analytics) ---")
        process_dc_pipeline(scope, conn, now_str)

    conn.commit()
    export_web_json(conn, "docs/data.json")
    conn.close()
    print(f"All 4 JP Datacenters pipeline completed (Enriched Analytics, Threshold >= {VELOCITY_THRESHOLD})!")

if __name__ == "__main__":
    fetch_and_save_all()
