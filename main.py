import requests
import sqlite3
import os
import json
import time
import re
from datetime import datetime, timezone

JP_DATACENTERS = ["Elemental", "Gaia", "Mana", "Meteor"]
VELOCITY_THRESHOLD = 50.0

KNOWN_70_ITEMS = {
    49234: ("剛力の心酔薬G4", True),
    49235: ("活力の心酔薬G4", True),
    49236: ("器用の心酔薬G4", True),
    49237: ("敏捷の心酔薬G4", True),
    49238: ("知力の心酔薬G4", True),
    49239: ("精神の心酔薬G4", True),
    49240: ("心力の心酔薬G4", True),
    49229: ("フトコーラ", True),
    49209: ("セドライト", False),
    47701: ("トラルコーン", False),
    47740: ("コザマル・カモミール", False),
    49230: ("キャロットラペ", True),
    49225: ("ローストチキン", True),
    49226: ("メスカル", True),
    49227: ("ベラフディアン・ペペロンチーノ", True),
    49228: ("コンチャ", True),
    49205: ("ロイヤルウパー", False),
    49206: ("スイートバナナ", False),
    49207: ("サンチアゴトマト", False),
    49208: ("ウカマウピメント", False),
    45972: ("オルコクロマイト", False),
    45984: ("クラロウォルナット原木", False),
    46188: ("シデリティス茶葉", False),
    50414: ("アイギス・エネルギーパック", False),
    52254: ("カード:ノーマカー", False),
}

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
        max_price INTEGER DEFAULT 0,
        avg_price REAL,
        units_for_sale INTEGER,
        listings_count INTEGER,
        last_upload_time TEXT
    )
    """)
    
    conn.commit()
    return conn

def clean_name(raw_name):
    return re.sub(r'\s*\[(NQ|HQ)\]\s*$', '', raw_name).strip()

def resolve_item_metadata_batch(item_ids):
    headers = {"User-Agent": "FFXIV-Market-Tracker/1.0"}
    meta_map = {}
    
    for iid in item_ids:
        if iid in KNOWN_70_ITEMS:
            name, can_hq = KNOWN_70_ITEMS[iid]
            meta_map[iid] = {"name": name, "can_be_hq": can_hq}

    missing_ids = [x for x in item_ids if x not in meta_map]
    for iid in missing_ids:
        try:
            x_single = f"https://xivapi.com/Item/{iid}?language=ja"
            xr = requests.get(x_single, headers=headers, timeout=3)
            if xr.status_code == 200:
                xdata = xr.json()
                name = xdata.get("Name_ja")
                can_hq = bool(xdata.get("CanBeHq", 0))
                if name:
                    meta_map[iid] = {"name": clean_name(name), "can_be_hq": can_hq}
                    continue
        except Exception:
            pass

        try:
            g_url = f"https://www.garlandtools.org/db/doc/item/ja/3/{iid}.json"
            gr = requests.get(g_url, headers=headers, timeout=3)
            if gr.status_code == 200:
                g_data = gr.json()
                name = g_data.get('item', {}).get('name')
                if name:
                    meta_map[iid] = {"name": clean_name(name), "can_be_hq": True}
        except Exception:
            pass
            
        time.sleep(0.05)
        
    return meta_map

def export_web_json(conn, output_path="docs/data.json"):
    os.makedirs("docs", exist_ok=True)
    cursor = conn.cursor()
    
    raw_data_by_scope = {}
    item_cross_dc = {}
    
    for scope in JP_DATACENTERS:
        cursor.execute("""
        SELECT ml.timestamp, ml.scope, ml.item_key, ml.item_id, ml.item_name, ml.quality,
               ml.daily_sale_velocity, ml.min_price, ml.max_price, ml.avg_price,
               ml.units_for_sale, ml.last_upload_time
        FROM market_logs ml
        INNER JOIN (
            SELECT scope, item_key, MAX(id) as max_id
            FROM market_logs
            WHERE scope = ?
            GROUP BY item_key
        ) latest ON ml.id = latest.max_id
        WHERE ml.daily_sale_velocity >= ?
        ORDER BY ml.daily_sale_velocity DESC
        """, (scope, VELOCITY_THRESHOLD))
        
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
                "max_price": r[8],
                "avg_price": r[9],
                "units_for_sale": r[10],
                "last_upload_time": r[11]
            }
            items.append(item_obj)
            
            ikey = r[2]
            if ikey not in item_cross_dc:
                item_cross_dc[ikey] = []
            item_cross_dc[ikey].append({
                "scope": r[1],
                "min_price": r[7],
                "velocity": r[6]
            })
            
        raw_data_by_scope[scope] = items

    cross_analytics = {}
    for ikey, dc_list in item_cross_dc.items():
        valid_prices = [x for x in dc_list if x["min_price"] > 0]
        if len(valid_prices) >= 2:
            sorted_by_price = sorted(valid_prices, key=lambda x: x["min_price"])
            cheapest = sorted_by_price[0]
            highest = sorted_by_price[-1]
            
            cheap_price = cheapest["min_price"]
            high_price = highest["min_price"]
            
            profit_gil = int(high_price * 0.95 - cheap_price)
            profit_rate = round((profit_gil / cheap_price) * 100, 1) if cheap_price > 0 else 0.0
            
            if profit_gil > 0 and profit_rate >= 5.0:
                cross_analytics[ikey] = {
                    "cheap_scope": cheapest["scope"],
                    "cheap_price": cheap_price,
                    "high_scope": highest["scope"],
                    "high_price": high_price,
                    "profit_gil": profit_gil,
                    "profit_rate": profit_rate
                }

    final_data_by_scope = {}
    for scope, items in raw_data_by_scope.items():
        enriched_items = []
        for item in items:
            ikey = item["item_key"]
            cross_info = cross_analytics.get(ikey)
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
        detail_url = f"https://universalis.app/api/v2/{scope_name}/{ids_str}"
        
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
    name_map = resolve_item_metadata_batch(all_item_ids)

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

        units_for_sale = data.get("unitsForSale", 0)

        # 直近取引履歴 (recentHistory) からの最低取引額、最高取引額、平均取引額を正確に算出
        history = data.get("recentHistory", [])
        if history:
            prices = [h.get("pricePerUnit", 0) for h in history if h.get("pricePerUnit", 0) > 0]
            if prices:
                hist_min = min(prices)
                hist_max = max(prices)
                hist_avg = round(sum(prices) / len(prices), 1)
            else:
                hist_min = data.get("minPrice", 0)
                hist_max = data.get("maxPrice", hist_min)
                hist_avg = round(data.get("averagePrice", hist_min), 1)
        else:
            hist_min = data.get("minPrice", 0)
            hist_max = data.get("maxPrice", hist_min)
            hist_avg = round(data.get("averagePrice", hist_min), 1)

        nq_vel = float(data.get("nqSaleVelocity") or 0.0)
        hq_vel = float(data.get("hqSaleVelocity") or 0.0)
        total_vel = float(data.get("dailySaleVelocity") or data.get("regularSaleVelocity") or 0.0)

        has_hq = can_be_hq or (hq_vel > 0)

        if not has_hq:
            qualities = [("NONE", pure_name, total_vel, hist_min, hist_max, hist_avg)]
        else:
            qualities = [
                ("NQ", f"{pure_name} [NQ]", nq_vel, hist_min, hist_max, hist_avg),
                ("HQ", f"{pure_name} [HQ]", hq_vel, hist_min, hist_max, hist_avg)
            ]

        for q_type, item_display_name, vel, h_min, h_max, h_avg in qualities:
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
                    daily_sale_velocity, min_price, max_price, avg_price,
                    units_for_sale, listings_count, last_upload_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """, (
                    now_str, scope_name, item_key, item_id, item_display_name, q_type,
                    vel, h_min, h_max, h_avg, units_for_sale, last_upload_str
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
        print(f"--- Processing DC: {scope} (Recent History Min/Max/Avg) ---")
        process_dc_pipeline(scope, conn, now_str)

    conn.commit()
    export_web_json(conn, "docs/data.json")
    conn.close()
    print(f"All 4 JP Datacenters pipeline completed (Threshold >= {VELOCITY_THRESHOLD})!")

if __name__ == "__main__":
    fetch_and_save_all()
