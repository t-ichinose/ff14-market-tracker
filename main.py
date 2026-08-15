import sqlite3
import requests
import json
import os
import sys
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

JP_DATACENTERS = ["Mana", "Elemental", "Gaia", "Meteor"]
DC_WORLDS = {
    "Mana": ["Anima", "Asura", "Chocobo", "Hades", "Ixion", "Masamune", "Pandaemonium", "Titan"],
    "Elemental": ["Carbuncle", "Gungnir", "Kujata", "Typhon", "Atomos", "Tonberry", "Aegis", "Garuda"],
    "Gaia": ["Alexander", "Bahamut", "Durandal", "Fenrir", "Ifrit", "Ridill", "Tiamat", "Ultima"],
    "Meteor": ["Belias", "Mandragora", "Ramuh", "Shinryu", "Unicorn", "Valefor", "Yojimbo", "Zeromus"]
}
WORLD_TO_DC = {w: dc for dc, worlds in DC_WORLDS.items() for w in worlds}
DEFAULT_HEADERS = {'User-Agent': 'FF14MarketTracker/2.0'}

def init_db(db_path="data/market_data.db"):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60.0)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS items_pool (
        item_id INTEGER PRIMARY KEY,
        added_at TEXT
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS items_metadata (
        item_id INTEGER PRIMARY KEY,
        item_name TEXT,
        icon_url TEXT,
        category_name TEXT,
        fetched_at TEXT
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sales_history (
        item_id INTEGER,
        world_name TEXT,
        timestamp INTEGER,
        price_per_unit INTEGER,
        quantity INTEGER,
        hq INTEGER,
        buyer_name TEXT,
        PRIMARY KEY (item_id, world_name, timestamp, price_per_unit, quantity, hq, buyer_name)
    )""")

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
    )""")
    conn.commit()
    return conn

def get_items_search():
    p = "docs/items_search.json"
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
                return {int(k): v for k, v in d.items() if str(k).isdigit()}
        except Exception:
            pass
    return {}

def get_icons_map():
    p = "docs/icons_map.json"
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
                return {int(k): v for k, v in d.items() if str(k).isdigit()}
        except Exception:
            pass
    return {}

def compute_xivapi_icon_url(icon_id: int) -> str:
    try:
        iid = int(icon_id)
        folder_num = (iid // 1000) * 1000
        folder_str = f"{folder_num:06d}"
        icon_str = f"{iid:06d}"
        return f"https://v2.xivapi.com/api/asset?path=ui/icon/{folder_str}/{icon_str}_hr1.tex&format=png"
    except Exception:
        return "https://v2.xivapi.com/api/asset?path=ui/icon/020000/021001_hr1.tex&format=png"

def resolve_item_metadata_batch(conn, item_ids):
    items_search = get_items_search()
    icons_map = get_icons_map()
    cursor = conn.cursor()

    default_icon = "https://v2.xivapi.com/api/asset?path=ui/icon/020000/021001_hr1.tex&format=png"
    meta_rows = []

    for iid in item_ids:
        name = items_search.get(iid, f"Item #{iid}")
        icon_url = icons_map.get(iid)
        if not icon_url:
            icon_url = compute_xivapi_icon_url(iid)
        meta_rows.append((iid, name, icon_url, "一般", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))

    cursor.executemany("""
    INSERT OR REPLACE INTO items_metadata (item_id, item_name, icon_url, category_name, fetched_at)
    VALUES (?, ?, ?, ?, ?)
    """, meta_rows)
    conn.commit()

def fetch_single_world_data(world_name, target_ids):
    headers = DEFAULT_HEADERS
    ids_str = ",".join(map(str, target_ids))
    detail_url = f"https://universalis.app/api/v2/{world_name}/{ids_str}?entries=500"
    for attempt in range(3):
        try:
            d_res = requests.get(detail_url, headers=headers, timeout=8)
            if d_res.status_code == 200:
                return world_name, d_res.json().get('items', {})
            elif d_res.status_code == 429:
                time.sleep(1)
        except Exception:
            time.sleep(0.5)
    return world_name, {}

def export_web_json(conn, output_path="docs/data.json"):
    cursor = conn.cursor()
    now_dt = datetime.now(timezone.utc)
    now_str = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    now_ts = int(now_dt.timestamp())
    seven_days_ago_ts = now_ts - (7 * 86400)

    items_search = get_items_search()
    icons_map = get_icons_map()

    cursor.execute("SELECT item_id, item_name, icon_url, category_name FROM items_metadata")
    meta_dict = {row[0]: {"name": row[1], "icon": row[2], "category": row[3]} for row in cursor.fetchall()}

    cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM sales_history WHERE timestamp >= ?", (seven_days_ago_ts,))
    ts_range = cursor.fetchone()
    if ts_range and ts_range[0] and ts_range[1]:
        calc_days = (ts_range[1] - ts_range[0]) / 86400.0
        actual_days = min(7.0, max(1.0, calc_days))
    else:
        actual_days = 7.0

    cursor.execute("""
    SELECT item_id, world_name, SUM(quantity) as total_qty, COUNT(*) as trade_count
    FROM sales_history
    WHERE timestamp >= ?
    GROUP BY item_id, world_name
    """, (seven_days_ago_ts,))
    velocity_calc = {(row[0], row[1]): round(row[2] / actual_days, 1) for row in cursor.fetchall()}

    cursor.execute("""
    SELECT item_id, world_name, price_per_unit 
    FROM sales_history 
    WHERE timestamp >= ?
    """, (seven_days_ago_ts,))
    sales_raw = {}
    for row in cursor.fetchall():
        sales_raw.setdefault((row[0], row[1]), []).append(row[2])

    sales_stats = {}
    for key, prices in sales_raw.items():
        min_p = min(prices)
        max_p = max(prices)
        if len(prices) >= 5:
            sp = sorted(prices)
            cut = max(1, int(len(sp) * 0.10))
            trimmed = sp[cut: len(sp) - cut] if (len(sp) - 2 * cut) > 0 else sp
            avg_p = round(sum(trimmed) / float(len(trimmed)))
        else:
            sp = sorted(prices)
            avg_p = sp[len(sp) // 2]
        sales_stats[key] = (min_p, avg_p, max_p, len(prices))

    cursor.execute("""
    SELECT item_id, world_name, dc_name, min_price, avg_price, max_price, units_for_sale, listings_count, sale_velocity, updated_at
    FROM item_market_stats
    """)
    rows = cursor.fetchall()

    data_by_world = {}
    for r in rows:
        iid, wname, dcname, min_p, avg_p, max_p, u_sale, l_count, vel, updated = r
        meta = meta_dict.get(iid, {})
        item_name = meta.get("name") or items_search.get(iid) or f"Item #{iid}"
        icon_url = icons_map.get(iid) or meta.get("icon") or compute_xivapi_icon_url(iid)
        category_name = meta.get("category", "一般")

        real_vel = velocity_calc.get((iid, wname), round(vel or 0, 1))
        if (iid, wname) in sales_stats:
            final_min, final_avg, final_max, hist_count = sales_stats[(iid, wname)]
        else:
            final_min, final_avg, final_max, hist_count = (min_p, avg_p, max_p, 0)

        daily_revenue = round(final_avg * real_vel) if hist_count > 0 else 0
        sale_trades = int(hist_count)

        item_obj = {
            "item_id": iid,
            "item_name": item_name,
            "icon_url": icon_url,
            "category_name": category_name,
            "min_price": final_min,
            "avg_price": final_avg,
            "max_price": final_max,
            "units_for_sale": u_sale,
            "listings_count": l_count,
            "sale_velocity": real_vel,
            "sale_trades": sale_trades,
            "daily_revenue": daily_revenue,
            "updated_at": updated
        }
        if sale_trades > 0:
            data_by_world.setdefault(wname, []).append(item_obj)

    final_data_by_world = {}
    for wname, items in data_by_world.items():
        filtered_items = [x for x in items if x["sale_velocity"] >= 10 or (2 <= x["item_id"] <= 19)]
        clean_high_value_items = [
            x for x in items 
            if x.get("max_price", 0) > 0 and ((x.get("avg_price", 0) / float(x["max_price"])) >= 0.35)
        ]
        top_by_max_price = set(x["item_id"] for x in sorted(clean_high_value_items, key=lambda x: x.get("max_price", 0), reverse=True)[:60])
        top_by_revenue = set(x["item_id"] for x in sorted(filtered_items, key=lambda x: x["daily_revenue"], reverse=True)[:60])
        top_by_velocity = set(x["item_id"] for x in sorted(filtered_items, key=lambda x: x["sale_velocity"], reverse=True)[:60])

        merged_top_ids = top_by_max_price.union(top_by_revenue).union(top_by_velocity)
        for cid in range(2, 20):
            merged_top_ids.add(cid)

        top_items = [x for x in items if x["item_id"] in merged_top_ids]
        top_items.sort(key=lambda x: x["sale_velocity"], reverse=True)
        final_data_by_world[wname] = top_items

    web_data = {
        "last_updated": now_str,
        "datacenters": JP_DATACENTERS,
        "dc_worlds": DC_WORLDS,
        "data": final_data_by_world
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(web_data, f, ensure_ascii=False, separators=(",", ":"))

    file_size_kb = os.path.getsize(output_path) / 1024
    print(f"Exported streamlined web JSON to {output_path} ({file_size_kb:.0f} KB)")

def fetch_and_save_all(target_dc=None):
    now_dt = datetime.now(timezone.utc)
    now_str = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = init_db("data/market_data.db")
    cursor = conn.cursor()
    headers = DEFAULT_HEADERS

    dcs = [target_dc] if target_dc and target_dc in JP_DATACENTERS else JP_DATACENTERS

    recent_ids_all = set()
    for dc in dcs:
        recent_url = f"https://universalis.app/api/v2/extra/stats/recently-updated?dcName={dc}"
        try:
            res = requests.get(recent_url, headers=headers, timeout=10)
            if res.ok:
                ids = res.json().get('items', [])[:200]
                recent_ids_all.update(ids)
        except Exception as e:
            print(f"[{dc}] Error fetching recent items: {e}")

    for cid in range(2, 20):
        recent_ids_all.add(cid)
    recent_ids_all.add(36047)

    if recent_ids_all:
        pool_batch = [(iid, now_str) for iid in recent_ids_all]
        cursor.executemany("INSERT OR IGNORE INTO items_pool (item_id, added_at) VALUES (?, ?)", pool_batch)
    conn.commit()

    target_ids = list(recent_ids_all)
    print(f"=== Ultra-Fast Pipeline: Fetching {len(target_ids)} active items across 32 worlds ===")

    target_worlds = []
    for dc in dcs:
        target_worlds.extend(DC_WORLDS.get(dc, []))

    chunk_size = 50
    item_chunks = [target_ids[i:i + chunk_size] for i in range(0, len(target_ids), chunk_size)]

    total_sales_inserted = 0
    total_stats_inserted = 0

    for chunk_idx, chunk_ids in enumerate(item_chunks, 1):
        world_results = {}
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(fetch_single_world_data, w, chunk_ids) for w in target_worlds]
            for future in as_completed(futures):
                w_name, w_items = future.result()
                world_results[w_name] = w_items

        sales_history_batch = []
        market_stats_batch = []

        for world_name in target_worlds:
            world_items_data = world_results.get(world_name, {})
            if not world_items_data:
                continue

            dc_name = WORLD_TO_DC.get(world_name, "Mana")

            for item_id_str, data in world_items_data.items():
                item_id = int(item_id_str)
                recent_history = data.get("recentHistory", [])[:500]
                for h in recent_history:
                    ts = h.get("timestamp", 0)
                    price = h.get("pricePerUnit", 0)
                    qty = h.get("quantity", 0)
                    hq = 1 if h.get("hq") else 0
                    buyer = h.get("buyerName", "")
                    if ts > 0 and price > 0:
                        sales_history_batch.append((item_id, world_name, ts, price, qty, hq, buyer))

                min_price = data.get("minPrice", 0)
                min_price_nq = data.get("minPriceNQ", 0)
                min_price_hq = data.get("minPriceHQ", 0)
                avg_price = data.get("averagePrice", 0)
                avg_price_nq = data.get("averagePriceNQ", 0)
                avg_price_hq = data.get("averagePriceHQ", 0)
                current_avg_price = data.get("currentAveragePrice", 0)
                current_avg_price_nq = data.get("currentAveragePriceNQ", 0)
                current_avg_price_hq = data.get("currentAveragePriceHQ", 0)
                max_price = data.get("maxPrice", 0)
                max_price_nq = data.get("maxPriceNQ", 0)
                max_price_hq = data.get("maxPriceHQ", 0)
                units_for_sale = data.get("unitsForSale", 0)
                listings_count = data.get("listingsCount", 0)
                units_sold = data.get("unitsSold", 0)
                recent_history_count = len(recent_history)
                sale_velocity = data.get("regularSaleVelocity", 0)
                sale_velocity_nq = data.get("nqSaleVelocity", 0)
                sale_velocity_hq = data.get("hqSaleVelocity", 0)

                market_stats_batch.append((
                    item_id, world_name, dc_name, now_str,
                    min_price, min_price_nq, min_price_hq,
                    avg_price, avg_price_nq, avg_price_hq,
                    current_avg_price, current_avg_price_nq, current_avg_price_hq,
                    max_price, max_price_nq, max_price_hq,
                    units_for_sale, listings_count,
                    units_sold, recent_history_count,
                    sale_velocity, sale_velocity_nq, sale_velocity_hq
                ))

        if sales_history_batch:
            cursor.executemany("""
            INSERT OR IGNORE INTO sales_history (item_id, world_name, timestamp, price_per_unit, quantity, hq, buyer_name)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, sales_history_batch)

        if market_stats_batch:
            cursor.executemany("""
            INSERT OR REPLACE INTO item_market_stats (
                item_id, world_name, dc_name, updated_at,
                min_price, min_price_nq, min_price_hq,
                avg_price, avg_price_nq, avg_price_hq,
                current_avg_price, current_avg_price_nq, current_avg_price_hq,
                max_price, max_price_nq, max_price_hq,
                units_for_sale, listings_count,
                units_sold, recent_history_count,
                sale_velocity, sale_velocity_nq, sale_velocity_hq
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, market_stats_batch)

        conn.commit()
        total_sales_inserted += len(sales_history_batch)
        total_stats_inserted += len(market_stats_batch)

    print(f"=== Ultra-Fast Pipeline Finished: {total_sales_inserted:,} sales & {total_stats_inserted:,} stats saved ===")

    cursor.execute("DELETE FROM sales_history WHERE timestamp < ?", (int(now_dt.timestamp()) - (7 * 86400),))
    conn.commit()

    cursor.execute("SELECT DISTINCT item_id FROM items_pool")
    all_pool_ids = [row[0] for row in cursor.fetchall()]
    if all_pool_ids:
        resolve_item_metadata_batch(conn, all_pool_ids)

    export_web_json(conn, "docs/data.json")
    conn.close()

if __name__ == "__main__":
    target_dc = None
    if len(sys.argv) > 1 and sys.argv[1] == "--dc":
        target_dc = sys.argv[2] if len(sys.argv) > 2 else "Mana"
    fetch_and_save_all(target_dc)
