import requests
import sqlite3
import os
import json
import time
import re
import sys
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

JP_DATACENTERS = ["Elemental", "Gaia", "Mana", "Meteor"]
DC_WORLDS = {
    "Elemental": ["Carbuncle", "Gungnir", "Kujata", "Typhon", "Atomos", "Tonberry", "Aegis", "Garuda"],
    "Gaia": ["Alexander", "Bahamut", "Durandal", "Fenrir", "Ifrit", "Ridill", "Tiamat", "Ultima"],
    "Mana": ["Anima", "Asura", "Chocobo", "Hades", "Ixion", "Masamune", "Pandaemonium", "Titan"],
    "Meteor": ["Belias", "Mandragora", "Ramuh", "Shinryu", "Unicorn", "Valefor", "Yojimbo", "Zeromus"]
}

WORLD_TO_DC = {}
for dc, worlds in DC_WORLDS.items():
    for w in worlds:
        WORLD_TO_DC[w] = dc

def init_db(db_path="data/market_data.db"):
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    
    # 1. アイテムプールシート (items_pool)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS items_pool (
        item_id INTEGER PRIMARY KEY,
        added_at TEXT
    )
    """)
    
    # 2. 取引履歴シート (sales_history)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sales_history (
        item_id INTEGER,
        world_name TEXT,
        timestamp INTEGER,
        price_per_unit INTEGER,
        quantity INTEGER,
        hq INTEGER,
        buyer_name TEXT,
        PRIMARY KEY (item_id, world_name, timestamp, buyer_name, price_per_unit, quantity)
    )
    """)
    
    # 3. 最新統計情報シート (item_market_stats)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS item_market_stats (
        item_id INTEGER,
        world_name TEXT,
        dc_name TEXT,
        updated_at TEXT,
        min_price INTEGER,
        min_price_nq INTEGER,
        min_price_hq INTEGER,
        avg_price REAL,
        avg_price_nq REAL,
        avg_price_hq REAL,
        current_avg_price REAL,
        current_avg_price_nq REAL,
        current_avg_price_hq REAL,
        max_price INTEGER,
        max_price_nq INTEGER,
        max_price_hq INTEGER,
        units_for_sale INTEGER,
        listings_count INTEGER,
        units_sold INTEGER,
        recent_history_count INTEGER,
        sale_velocity REAL,
        sale_velocity_nq REAL,
        sale_velocity_hq REAL,
        PRIMARY KEY (item_id, world_name)
    )
    """)
    
    # 4. アイテムマスターシート (items_metadata)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS items_metadata (
        item_id INTEGER PRIMARY KEY,
        item_name TEXT,
        icon_url TEXT,
        category_name TEXT,
        fetched_at TEXT
    )
    """)
    
    conn.commit()
    return conn

def cleanup_old_logs(conn, days=7):
    """Delete sales history older than `days` days."""
    try:
        cursor = conn.cursor()
        cutoff_ts = int(time.time()) - (days * 86400)
        cursor.execute("DELETE FROM sales_history WHERE timestamp < ?", (cutoff_ts,))
        deleted_count = cursor.rowcount
        conn.commit()
        if deleted_count > 0:
            print(f"[Cleanup] Deleted {deleted_count} trade logs older than {days} days.")
    except Exception as e:
        print(f"[Cleanup] Error cleaning up old logs: {e}")

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
                    items[str(iid)] = name
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        print(f"Exported full items search index ({len(items)} items) to {output_path}")
    except Exception as e:
        print(f"Error building items_search.json: {e}")

def load_items_search():
    ensure_items_search_json("docs/items_search.json")
    if os.path.exists("docs/items_search.json"):
        try:
            with open("docs/items_search.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def resolve_item_metadata_batch(conn, item_ids):
    headers = {"User-Agent": "FFXIV-Market-Tracker/1.0"}
    meta_map = {}
    
    items_search = load_items_search()
    cursor = conn.cursor()

    missing_ids = []
    for iid in item_ids:
        cursor.execute("SELECT item_name, icon_url, category_name FROM items_metadata WHERE item_id = ?", (iid,))
        row = cursor.fetchone()
        if row and row[0] and not row[0].startswith("アイテム #") and not "" in row[0] and len(row[0]) < 60 and not row[0].endswith("。") and not row[0].endswith("効"):
            meta_map[iid] = {"name": row[0], "icon": row[1], "category": row[2]}
        else:
            missing_ids.append(iid)

    if not missing_ids:
        return meta_map

    print(f"Resolving exact item names for {len(missing_ids)} items...")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for iid in missing_ids:
        name = items_search.get(str(iid)) or items_search.get(iid)
        icon_url = ""
        category_name = "一般"

        # Garland API fallback for icon and category
        try:
            res = requests.get(f"https://www.garlandtools.org/db/doc/item/ja/2/{iid}.json", headers=headers, timeout=5)
            if res.status_code == 200:
                res.encoding = 'utf-8'
                g_data = res.json().get("item", {})
                if not name:
                    name = g_data.get("name")
                icon_code = g_data.get("icon")
                if icon_code:
                    code_int = int(icon_code)
                    folder = f"{code_int:06d}"[:3] + "000"
                    icon_url = f"https://xivapi.com/i/{folder}/{code_int:06d}.png"
                category_name = g_data.get("category_name", category_name)
        except Exception:
            pass

        if not name:
            name = f"アイテム #{iid}"

        cursor.execute("""
        INSERT OR REPLACE INTO items_metadata (item_id, item_name, icon_url, category_name, fetched_at)
        VALUES (?, ?, ?, ?, ?)
        """, (iid, name, icon_url, category_name, now_str))

        meta_map[iid] = {"name": name, "icon": icon_url, "category": category_name}

    conn.commit()
    return meta_map

def fetch_single_world_data(world_name, target_ids):
    headers = {"User-Agent": "FFXIV-Market-Tracker/1.0"}
    world_items_data = {}
    chunk_size = 50
    chunks = [target_ids[i:i + chunk_size] for i in range(0, len(target_ids), chunk_size)]
    
    def fetch_chunk(chunk):
        ids_str = ",".join(map(str, chunk))
        detail_url = f"https://universalis.app/api/v2/{world_name}/{ids_str}?entriesToReturn=500"
        for attempt in range(2):
            try:
                d_res = requests.get(detail_url, headers=headers, timeout=10)
                if d_res.status_code == 200:
                    return d_res.json().get('items', {})
            except Exception:
                time.sleep(0.3)
        return {}

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(fetch_chunk, c) for c in chunks]
        for future in as_completed(futures):
            res = future.result()
            if res:
                world_items_data.update(res)
                
    return world_name, world_items_data

def process_dc_pipeline(scope_name: str, conn, now_str: str):
    headers = {"User-Agent": "FFXIV-Market-Tracker/1.0"}
    cursor = conn.cursor()
    target_worlds = DC_WORLDS.get(scope_name, [])

    # Step 1: 200件の直近取引アイテムIDを取得
    recent_url = f"https://universalis.app/api/v2/extra/stats/recently-updated?dcName={scope_name}"
    try:
        res = requests.get(recent_url, headers=headers, timeout=10)
        res.raise_for_status()
        recent_items = res.json().get('items', [])[:200]
    except Exception as e:
        print(f"[{scope_name}] Step 1 Error: {e}")
        recent_items = []

    # ① プールシート (items_pool) に追加登録
    for iid in recent_items:
        cursor.execute("INSERT OR IGNORE INTO items_pool (item_id, added_at) VALUES (?, ?)", (iid, now_str))
    conn.commit()

    # ② プールに入っている全アイテムIDを取得
    cursor.execute("SELECT item_id FROM items_pool")
    target_ids = [row[0] for row in cursor.fetchall()]
    if not target_ids:
        return

    print(f"  [Parallel] Fetching {len(target_worlds)} worlds concurrently ({len(target_ids)} pooled items)...")
    world_results = {}
    with ThreadPoolExecutor(max_workers=len(target_worlds)) as executor:
        futures = [executor.submit(fetch_single_world_data, w, target_ids) for w in target_worlds]
        for future in as_completed(futures):
            w_name, w_items = future.result()
            world_results[w_name] = w_items

    # メタデータ一括解決
    resolve_item_metadata_batch(conn, target_ids)

    # 各ワールド・各アイテムのデータ書き込み
    for world_name in target_worlds:
        world_items_data = world_results.get(world_name, {})
        if not world_items_data:
            continue

        dc_name = WORLD_TO_DC.get(world_name, scope_name)

        for item_id_str, data in world_items_data.items():
            item_id = int(item_id_str)

            # 1) 取引履歴シート (sales_history) への追記 (INSERT OR IGNORE)
            recent_history = data.get("recentHistory", [])
            for h in recent_history:
                ts = h.get("timestamp", 0)
                price = h.get("pricePerUnit", 0)
                qty = h.get("quantity", 0)
                hq = 1 if h.get("hq") else 0
                buyer = h.get("buyerName", "")
                if ts > 0 and price > 0:
                    cursor.execute("""
                    INSERT OR IGNORE INTO sales_history (item_id, world_name, timestamp, price_per_unit, quantity, hq, buyer_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (item_id, world_name, ts, price, qty, hq, buyer))

            # 2) 最新統計情報シート (item_market_stats) への保存 (INSERT OR REPLACE)
            cursor.execute("""
            INSERT OR REPLACE INTO item_market_stats (
                item_id, world_name, dc_name, updated_at,
                min_price, min_price_nq, min_price_hq,
                avg_price, avg_price_nq, avg_price_hq,
                current_avg_price, current_avg_price_nq, current_avg_price_hq,
                max_price, max_price_nq, max_price_hq,
                units_for_sale, listings_count, units_sold, recent_history_count,
                sale_velocity, sale_velocity_nq, sale_velocity_hq
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item_id, world_name, dc_name, now_str,
                data.get("minPrice", 0), data.get("minPriceNQ", 0), data.get("minPriceHQ", 0),
                data.get("averagePrice", 0.0), data.get("averagePriceNQ", 0.0), data.get("averagePriceHQ", 0.0),
                data.get("currentAveragePrice", 0.0), data.get("currentAveragePriceNQ", 0.0), data.get("currentAveragePriceHQ", 0.0),
                data.get("maxPrice", 0), data.get("maxPriceNQ", 0), data.get("maxPriceHQ", 0),
                data.get("unitsForSale", 0), data.get("listingsCount", 0),
                data.get("unitsSold", 0), data.get("recentHistoryCount", 0),
                data.get("regularSaleVelocity", 0.0), data.get("nqSaleVelocity", 0.0), data.get("hqSaleVelocity", 0.0)
            ))

        print(f"  [{world_name}] Processed -> Items: {len(world_items_data)}")

    conn.commit()

def export_web_json(conn, output_path="docs/data.json"):
    cursor = conn.cursor()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # メタデータマップの作成
    cursor.execute("SELECT item_id, item_name, icon_url, category_name FROM items_metadata")
    meta_map = {row[0]: {"name": row[1], "icon": row[2], "category": row[3]} for row in cursor.fetchall()}

    # 過去7日間の取引履歴集計マップ (取引データから MIN, MAX, AVG, 7日合計/7.0)
    cutoff_ts = int(time.time()) - (7 * 86400)
    cursor.execute("""
    SELECT item_id, world_name,
           MIN(price_per_unit) as h_min,
           MAX(price_per_unit) as h_max,
           AVG(price_per_unit) as h_avg,
           SUM(quantity) as total_qty
    FROM sales_history
    WHERE timestamp >= ?
    GROUP BY item_id, world_name
    """, (cutoff_ts,))

    history_stats_map = {}
    for row in cursor.fetchall():
        iid, wname, h_min, h_max, h_avg, total_qty = row
        history_stats_map[(iid, wname)] = {
            "min_price": h_min or 0,
            "max_price": h_max or 0,
            "avg_price": round(h_avg or 0, 1),
            "sale_velocity": round((total_qty or 0) / 7.0, 1)  # 合算 / 7.0日
        }

    # 最新統計データ（在庫数等）の読み込み
    cursor.execute("SELECT item_id, world_name, dc_name, min_price, avg_price, max_price, units_for_sale, sale_velocity FROM item_market_stats")
    
    final_data_by_world = {}

    for row in cursor.fetchall():
        iid, wname, dc_name, stats_min, stats_avg, stats_max, units_for_sale, stats_vel = row

        item_meta = meta_map.get(iid, {"name": f"アイテム #{iid}", "icon": "", "category": "一般"})
        hist_stats = history_stats_map.get((iid, wname), None)

        # 取引データ(sales_history)からの計算値を最優先、なければ統計データ値を採用
        if hist_stats:
            c_min = hist_stats["min_price"]
            c_avg = hist_stats["avg_price"]
            c_max = hist_stats["max_price"]
            c_vel = hist_stats["sale_velocity"]
        else:
            c_min = stats_min
            c_avg = round(stats_avg, 1)
            c_max = stats_max
            c_vel = round(stats_vel, 1)

        card_item = {
            "item_id": iid,
            "item_name": item_meta["name"],
            "icon_url": item_meta["icon"],
            "category_name": item_meta["category"],
            "world_name": wname,
            "dc_name": dc_name,
            "min_price": c_min,
            "avg_price": c_avg,
            "max_price": c_max,
            "units_for_sale": units_for_sale or 0,
            "sale_velocity": c_vel
        }

        if wname not in final_data_by_world:
            final_data_by_world[wname] = []
        final_data_by_world[wname].append(card_item)

    web_data = {
        "last_updated": now_str,
        "datacenters": JP_DATACENTERS,
        "dc_worlds": DC_WORLDS,
        "data": final_data_by_world
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(web_data, f, ensure_ascii=False, indent=2)

    print(f"Exported streamlined web JSON to {output_path}")

    web_data = {
        "last_updated": now_str,
        "datacenters": JP_DATACENTERS,
        "dc_worlds": DC_WORLDS,
        "data": final_data_by_world
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(web_data, f, ensure_ascii=False, indent=2)

    print(f"Exported enriched web JSON to {output_path}")

def fetch_and_save_all(target_dc=None):
    db_path = "data/market_data.db"
    conn = init_db(db_path)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    dcs = [target_dc] if target_dc and target_dc in JP_DATACENTERS else JP_DATACENTERS

    for scope in dcs:
        print(f"--- Processing DC & All Worlds Direct: {scope} (Parallel) ---")
        try:
            process_dc_pipeline(scope, conn, now_str)
            export_web_json(conn, "docs/data.json")
        except Exception as e:
            print(f"[{scope}] Error in pipeline: {e}")

    cleanup_old_logs(conn, 7)
    conn.commit()
    export_web_json(conn, "docs/data.json")

if __name__ == "__main__":
    target_dc = None
    if len(sys.argv) > 1 and sys.argv[1] == "--dc":
        target_dc = sys.argv[2] if len(sys.argv) > 2 else "Mana"
    fetch_and_save_all(target_dc)
