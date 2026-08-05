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
        avg_price REAL,
        hist_min INTEGER DEFAULT 0,
        hist_max INTEGER DEFAULT 0,
        units_for_sale INTEGER,
        listings_count INTEGER,
        last_upload_time TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS item_metadata (
        item_id INTEGER PRIMARY KEY,
        icon_url TEXT,
        description TEXT,
        category TEXT,
        item_level INTEGER DEFAULT 0,
        shop_price INTEGER DEFAULT 0,
        buyback_price INTEGER DEFAULT 0,
        stack_size INTEGER DEFAULT 1,
        can_be_hq INTEGER DEFAULT 0,
        rarity INTEGER DEFAULT 1,
        fetched_at TEXT
    )
    """)
    
    conn.commit()
    return conn

def clean_name(raw_name):
    return re.sub(r'\s*\[(NQ|HQ)\]\s*$', '', raw_name).strip()

def resolve_item_metadata_batch(conn, item_ids):
    headers = {"User-Agent": "FFXIV-Market-Tracker/1.0"}
    meta_map = {}
    
    # Load full 16,843 items search dictionary if available
    items_search = {}
    if os.path.exists("docs/items_search.json"):
        try:
            with open("docs/items_search.json", "r", encoding="utf-8") as f:
                items_search = json.load(f)
        except Exception:
            pass

    # 1. Known items map & items_search dictionary
    for iid in item_ids:
        if iid in KNOWN_70_ITEMS:
            name, can_hq = KNOWN_70_ITEMS[iid]
            meta_map[iid] = {"name": name, "can_be_hq": can_hq}
        elif str(iid) in items_search:
            meta_map[iid] = {"name": items_search[str(iid)], "can_be_hq": True}
        elif iid in items_search:
            meta_map[iid] = {"name": items_search[iid], "can_be_hq": True}

    # 2. Check item_metadata DB cache for any remaining
    missing_ids = [x for x in item_ids if x not in meta_map]
    if missing_ids and conn:
        cursor = conn.cursor()
        placeholders = ','.join(['?'] * len(missing_ids))
        cursor.execute(f"SELECT item_id, category, can_be_hq FROM item_metadata WHERE item_id IN ({placeholders})", list(missing_ids))
        for row in cursor.fetchall():
            meta_map[row[0]] = {"name": f"Unknown ({row[0]})", "can_be_hq": bool(row[2])}

    # 3. Fallback to XIVAPI / Garland for truly unknown items
    still_missing = [x for x in item_ids if x not in meta_map]
    for iid in still_missing:
        try:
            x_single = f"https://xivapi.com/Item/{iid}?language=ja"
            xr = requests.get(x_single, headers=headers, timeout=5)
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
            gr = requests.get(g_url, headers=headers, timeout=5)
            if gr.status_code == 200:
                g_data = gr.json()
                name = g_data.get('item', {}).get('name')
                if name:
                    meta_map[iid] = {"name": clean_name(name), "can_be_hq": True}
        except Exception:
            pass
            
        time.sleep(0.05)
        
    return meta_map

def fetch_and_cache_metadata(conn, item_ids):
    """Fetch item metadata from XIVAPI/Garland, cache in DB, return dict."""
    if not item_ids:
        return {}
        
    headers = {"User-Agent": "FFXIV-Market-Tracker/1.0"}
    cursor = conn.cursor()
    
    # Load existing cache
    cached = {}
    placeholders = ','.join(['?'] * len(item_ids))
    cursor.execute(f"SELECT * FROM item_metadata WHERE item_id IN ({placeholders})", list(item_ids))
    for row in cursor.fetchall():
        cached[row[0]] = {
            "icon_url": row[1] or "",
            "description": row[2] or "",
            "category": row[3] or "",
            "item_level": row[4] or 0,
            "shop_price": row[5] or 0,
            "buyback_price": row[6] or 0,
            "stack_size": row[7] or 1,
            "can_be_hq": bool(row[8]),
            "rarity": row[9] or 1
        }
    
    missing = [iid for iid in item_ids if iid not in cached]
    if not missing:
        print(f"[Metadata] All {len(item_ids)} items cached, no API calls needed.")
        return cached
    
    print(f"[Metadata] {len(cached)} cached, {len(missing)} new items to fetch...")
    
    for iid in missing:
        meta = None
        
        # Try XIVAPI first
        try:
            url = f"https://xivapi.com/Item/{iid}?language=ja"
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                xdata = resp.json()
                icon_path = xdata.get("IconHD") or xdata.get("Icon", "")
                icon_url = f"https://xivapi.com{icon_path}" if icon_path else ""
                cat_obj = xdata.get("ItemUICategory")
                category = ""
                if cat_obj and isinstance(cat_obj, dict):
                    category = cat_obj.get("Name_ja", "") or cat_obj.get("Name", "") or ""
                meta = {
                    "icon_url": icon_url,
                    "description": (xdata.get("Description_ja") or xdata.get("Description") or "").strip(),
                    "category": category,
                    "item_level": xdata.get("LevelItem", 0) or 0,
                    "shop_price": xdata.get("PriceMid", 0) or 0,
                    "buyback_price": xdata.get("PriceLow", 0) or 0,
                    "stack_size": xdata.get("StackSize", 1) or 1,
                    "can_be_hq": bool(xdata.get("CanBeHq", 0)),
                    "rarity": xdata.get("Rarity", 1) or 1
                }
        except Exception:
            pass
        
        # Fallback to Garland Tools
        if not meta:
            try:
                url = f"https://www.garlandtools.org/db/doc/item/ja/3/{iid}.json"
                resp = requests.get(url, headers=headers, timeout=5)
                if resp.status_code == 200:
                    item_data = resp.json().get("item", {})
                    icon_id = item_data.get("icon", "")
                    icon_url = f"https://www.garlandtools.org/files/icons/item/{icon_id}.png" if icon_id else ""
                    meta = {
                        "icon_url": icon_url,
                        "description": (item_data.get("description", "") or "").strip(),
                        "category": str(item_data.get("category", "") or ""),
                        "item_level": item_data.get("ilvl", 0) or 0,
                        "shop_price": item_data.get("price", 0) or 0,
                        "buyback_price": 0,
                        "stack_size": item_data.get("stackSize", 1) or 1,
                        "can_be_hq": bool(item_data.get("hq", 0)),
                        "rarity": item_data.get("rarity", 1) or 1
                    }
            except Exception:
                pass
        
        if meta:
            cached[iid] = meta
            now_str = datetime.now(timezone.utc).isoformat()
            cursor.execute("""
                INSERT OR REPLACE INTO item_metadata 
                (item_id, icon_url, description, category, item_level, shop_price, buyback_price, stack_size, can_be_hq, rarity, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (iid, meta["icon_url"], meta["description"], meta["category"],
                   meta["item_level"], meta["shop_price"], meta["buyback_price"],
                   meta["stack_size"], int(meta["can_be_hq"]), meta["rarity"], now_str))
            print(f"  [Metadata] {iid} -> {meta['category']} (IL{meta['item_level']})")
        else:
            print(f"  [Metadata] {iid} -> Failed to fetch")
        
        time.sleep(0.08)
    
    conn.commit()
    print(f"[Metadata] Fetched and cached {len(missing)} new items.")
    return cached

def export_web_json(conn, output_path="docs/data.json"):
    os.makedirs("docs", exist_ok=True)
    cursor = conn.cursor()
    
    raw_data_by_scope = {}
    item_cross_dc = {}
    
    for scope in JP_DATACENTERS:
        cursor.execute("""
        SELECT ml.timestamp, ml.scope, ml.item_key, ml.item_id, ml.item_name, ml.quality,
               ml.daily_sale_velocity, ml.min_price, ml.avg_price, ml.hist_min, ml.hist_max,
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
            min_p = r[7]
            h_min = r[9] if (r[9] and r[9] > 0) else min_p
            h_max = r[10] if (r[10] and r[10] >= h_min) else h_min
            h_avg = r[8] if r[8] else h_min

            if h_avg < h_min: h_avg = float(h_min)
            if h_avg > h_max: h_avg = float(h_max)

            item_id = r[3]
            raw_name = clean_name(r[4])
            if (raw_name.startswith("Item ") or "Unknown" in raw_name) and str(item_id) in items_search:
                raw_name = items_search[str(item_id)]
            elif (raw_name.startswith("Item ") or "Unknown" in raw_name) and item_id in items_search:
                raw_name = items_search[item_id]

            raw_name = clean_name(raw_name)

            item_obj = {
                "timestamp": r[0],
                "scope": r[1],
                "item_key": r[2],
                "item_id": item_id,
                "item_name": raw_name,
                "quality": r[5],
                "velocity": r[6],
                "min_price": min_p,
                "avg_price": h_avg,
                "hist_min": h_min,
                "hist_max": h_max,
                "units_for_sale": r[11],
                "last_upload_time": r[12]
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

    # Collect all unique item IDs for metadata
    all_item_ids = set()
    for scope, items in raw_data_by_scope.items():
        for item in items:
            all_item_ids.add(item["item_id"])
    
    # Fetch/cache metadata for all items
    meta_cache = fetch_and_cache_metadata(conn, all_item_ids)

    final_data_by_scope = {}
    for scope, items in raw_data_by_scope.items():
        enriched_items = []
        for item in items:
            ikey = item["item_key"]
            cross_info = cross_analytics.get(ikey)
            item["cross_info"] = cross_info
            # Attach metadata
            if item["item_id"] in meta_cache:
                item["meta"] = meta_cache[item["item_id"]]
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
    ensure_items_search_json("docs/items_search.json")

def ensure_items_search_json(output_path="docs/items_search.json"):
    if os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
        return
    print("Building docs/items_search.json index (16,843 marketable items)...")
    try:
        import csv, io
        headers = {"User-Agent": "FFXIV-Market-Tracker/1.0"}
        marketable = set(requests.get('https://universalis.app/api/v2/marketable', headers=headers, timeout=10).json())
        text = requests.get('https://raw.githubusercontent.com/xivapi/ffxiv-datamining/master/csv/ja/Item.csv', headers=headers, timeout=15).content.decode('utf-8')
        reader = csv.reader(io.StringIO(text))
        next(reader)
        next(reader)
        items = {}
        for r in reader:
            if r[0].isdigit():
                iid = int(r[0])
                name = r[1].strip()
                if iid in marketable and name:
                    items[iid] = name
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)
        print(f"Exported full items search index ({len(items)} items) to {output_path}")
    except Exception as e:
        print(f"Error building items_search.json: {e}")

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
    chunk_size = 50
    for i in range(0, len(target_ids), chunk_size):
        chunk = target_ids[i:i + chunk_size]
        ids_str = ",".join(map(str, chunk))
        detail_url = f"https://universalis.app/api/v2/{scope_name}/{ids_str}?entriesToReturn=100"
        
        for attempt in range(2):
            try:
                d_res = requests.get(detail_url, headers=headers, timeout=15)
                if d_res.status_code == 200:
                    items_data.update(d_res.json().get('items', {}))
                    break
            except Exception as e:
                if attempt == 1:
                    print(f"[{scope_name}] Detail fetch error (attempt {attempt+1}): {e}")
                time.sleep(1)
            
        time.sleep(0.1)

    if not items_data:
        return

    all_item_ids = [int(k) for k in items_data.keys()]
    name_map = resolve_item_metadata_batch(conn, all_item_ids)

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

        # その列(データセンター)で今マーケットに出品されているリアルな総個数！
        listings = data.get("listings", [])
        exact_dc_stock = sum(l.get("quantity", 0) for l in listings) if listings else data.get("unitsForSale", 0)

        history = data.get("recentHistory", [])
        prices = [h.get("pricePerUnit", 0) for h in history if h.get("pricePerUnit", 0) > 0]
        
        if prices:
            h_min = min(prices)
            h_max = max(prices)
            h_avg = round(sum(prices) / len(prices), 1)
        else:
            h_min = data.get("minPrice", 0)
            h_max = data.get("maxPrice", h_min)
            h_avg = round(data.get("averagePrice", h_min), 1)

        if h_avg < h_min: h_avg = float(h_min)
        if h_avg > h_max: h_avg = float(h_max)

        nq_vel = float(data.get("nqSaleVelocity") or 0.0)
        hq_vel = float(data.get("hqSaleVelocity") or 0.0)
        total_vel = float(data.get("dailySaleVelocity") or data.get("regularSaleVelocity") or 0.0)
        
        nq_min = data.get("minPriceNQ") or data.get("minPrice", 0)
        hq_min = data.get("minPriceHQ") or 0

        has_hq = can_be_hq or (hq_vel > 0)

        if not has_hq:
            qualities = [("NONE", pure_name, total_vel, nq_min, h_min, h_max, h_avg)]
        else:
            qualities = [
                ("NQ", f"{pure_name} [NQ]", nq_vel, nq_min, h_min, h_max, h_avg),
                ("HQ", f"{pure_name} [HQ]", hq_vel, hq_min, h_min, h_max, h_avg)
            ]

        for q_type, item_display_name, vel, price, hm_min, hm_max, hm_avg in qualities:
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
                    daily_sale_velocity, min_price, avg_price, hist_min, hist_max,
                    units_for_sale, listings_count, last_upload_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """, (
                    now_str, scope_name, item_key, item_id, item_display_name, q_type,
                    vel, price, hm_avg, hm_min, hm_max, exact_dc_stock, last_upload_str
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
        print(f"--- Processing DC: {scope} (Exact DC Listings Stock) ---")
        process_dc_pipeline(scope, conn, now_str)

    conn.commit()
    export_web_json(conn, "docs/data.json")
    conn.close()
    print(f"All 4 JP Datacenters pipeline completed (Threshold >= {VELOCITY_THRESHOLD})!")

if __name__ == "__main__":
    fetch_and_save_all()
