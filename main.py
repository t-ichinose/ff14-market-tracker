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
DEFAULT_HEADERS = {'User-Agent': 'FF14MarketTracker/3.0'}

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

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_lookup ON sales_history (item_id, world_name, timestamp);")

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
    detail_url = f"https://universalis.app/api/v2/{world_name}/{ids_str}?entries=50"
    for attempt in range(4):
        try:
            d_res = requests.get(detail_url, headers=headers, timeout=12)
            if d_res.status_code == 200:
                return world_name, d_res.json().get('items', {})
            print(f"⚠️ [{world_name}] API HTTP {d_res.status_code}. Retrying ({attempt + 1}/4)...")
            time.sleep(1.0 * (2 ** attempt))
        except Exception as e:
            print(f"⚠️ [{world_name}] Network Error ({e}). Retrying ({attempt + 1}/4)...")
            time.sleep(1.0 * (2 ** attempt))
    print(f"❌ [API ERROR] Failed to fetch data for {world_name} after 4 attempts.")
    return world_name, {}

def export_web_json(conn, output_path="docs/data.json"):
    """
    Exports full web JSON directly from sales_history database.
    Calculates card stats and recent 15 transaction history for all worlds/DCs.
    """
    cursor = conn.cursor()
    now_dt = datetime.now(timezone.utc)
    now_str = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    now_ts = int(now_dt.timestamp())
    seven_days_ago_ts = now_ts - (7 * 86400)

    items_search = get_items_search()
    icons_map = get_icons_map()

    cursor.execute("SELECT item_id, item_name, icon_url, category_name FROM items_metadata")
    meta_dict = {row[0]: {"name": row[1], "icon": row[2], "category": row[3]} for row in cursor.fetchall()}

    # Calculate actual span of days in DB (up to 7.0 days)
    cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM sales_history WHERE timestamp >= ?", (seven_days_ago_ts,))
    ts_range = cursor.fetchone()
    if ts_range and ts_range[0] and ts_range[1]:
        calc_days = (ts_range[1] - ts_range[0]) / 86400.0
        actual_days = min(7.0, max(1.0, calc_days))
    else:
        actual_days = 7.0

    # Retrieve all transaction logs from sales_history within past 7 days
    cursor.execute("""
    SELECT item_id, world_name, price_per_unit, quantity, hq, timestamp, buyer_name
    FROM sales_history 
    WHERE timestamp >= ?
    ORDER BY timestamp DESC
    """, (seven_days_ago_ts,))

    sales_by_item_world = {}
    history_by_item_world = {}

    for row in cursor.fetchall():
        iid, wname, price, qty, hq, ts, buyer = row
        sales_by_item_world.setdefault((iid, wname), []).append({"price": price, "qty": qty, "ts": ts})
        
        hist_list = history_by_item_world.setdefault((iid, wname), [])
        if len(hist_list) < 50:
            hist_list.append({
                "price": price,
                "qty": qty,
                "hq": bool(hq),
                "ts": ts,
                "buyer": buyer or ""
            })

    # Group calculated metrics by world
    data_by_world = {}

    for (iid, wname), items_list in sales_by_item_world.items():
        if not items_list:
            continue

        prices = [x["price"] for x in items_list]
        med = sorted(prices)[len(prices) // 2]
        
        # Outlier filtering for extreme money transfers / RMT
        if med < 1_000_000 and len(items_list) >= 2:
            clean_items = [x for x in items_list if not (x["price"] > 20 * med and x["price"] > 1_000_000)]
            if clean_items:
                items_list = clean_items

        clean_prices = [x["price"] for x in items_list]
        total_qty = sum(x["qty"] for x in items_list)
        trade_cnt = len(items_list)

        real_vel = round(total_qty / actual_days, 1)
        min_p = min(clean_prices)
        max_p = max(clean_prices)

        if len(clean_prices) >= 5:
            sp = sorted(clean_prices)
            cut = max(1, int(len(sp) * 0.10))
            trimmed = sp[cut: len(sp) - cut] if (len(sp) - 2 * cut) > 0 else sp
            avg_p = round(sum(trimmed) / float(len(trimmed)))
        else:
            sp = sorted(clean_prices)
            avg_p = sp[len(sp) // 2]

        daily_revenue = round(avg_p * real_vel)

        meta = meta_dict.get(iid, {})
        item_name = meta.get("name") or items_search.get(iid) or f"Item #{iid}"
        icon_url = icons_map.get(iid) or meta.get("icon") or compute_xivapi_icon_url(iid)
        category_name = meta.get("category", "一般")

        item_obj = {
            "item_id": iid,
            "item_name": item_name,
            "icon_url": icon_url,
            "category_name": category_name,
            "min_price": min_p,
            "avg_price": avg_p,
            "max_price": max_p,
            "sale_velocity": real_vel,
            "sale_trades": trade_cnt,
            "daily_revenue": daily_revenue,
            "history": history_by_item_world.get((iid, wname), []),
            "updated_at": now_str
        }

        data_by_world.setdefault(wname, []).append(item_obj)

    # Sort items per world by sale_velocity DESC
    for wname in data_by_world:
        data_by_world[wname].sort(key=lambda x: x["sale_velocity"], reverse=True)

    # Load existing docs/data.json if present, to preserve data for non-updated DCs
    merged_data_by_world = {}
    if os.path.exists(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                existing_json = json.load(f)
                merged_data_by_world = existing_json.get("data", {})
        except Exception as e:
            print(f"Notice: Could not load existing {output_path} for merging: {e}")

    # Update merged_data_by_world with freshly calculated worlds
    for wname, items in data_by_world.items():
        if items:
            merged_data_by_world[wname] = items

    web_data = {
        "last_updated": now_str,
        "datacenters": JP_DATACENTERS,
        "dc_worlds": DC_WORLDS,
        "data": merged_data_by_world
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(web_data, f, ensure_ascii=False, separators=(",", ":"))

    file_size_kb = os.path.getsize(output_path) / 1024
    print(f"Successfully exported clean merged web JSON to {output_path} ({file_size_kb:.0f} KB)")

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

    cursor.execute("SELECT item_id FROM items_pool WHERE item_id >= 100")
    existing_pool_ids = [row[0] for row in cursor.fetchall()]
    if not existing_pool_ids:
        items_search = get_items_search()
        existing_pool_ids = [iid for iid in items_search.keys() if iid >= 100]
    recent_ids_all.update(existing_pool_ids)

    recent_ids_all.add(36047)  # Example active item (魔導機械修理材 etc)

    if recent_ids_all:
        pool_batch = [(iid, now_str) for iid in recent_ids_all]
        cursor.executemany("INSERT OR IGNORE INTO items_pool (item_id, added_at) VALUES (?, ?)", pool_batch)
    conn.commit()

    target_ids = list(recent_ids_all)
    target_worlds = []
    for dc in dcs:
        target_worlds.extend(DC_WORLDS.get(dc, []))

    chunk_size = 100
    item_chunks = [target_ids[i:i + chunk_size] for i in range(0, len(target_ids), chunk_size)]
    all_tasks = [(world, chunk) for chunk in item_chunks for world in target_worlds]

    print(f"=== Fetching {len(target_ids)} items ({len(all_tasks)} tasks) across {len(target_worlds)} worlds ({','.join(dcs)}) ===")

    total_sales_inserted = 0
    failed_worlds = set()
    succeeded_worlds = set()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_single_world_data, world, chunk): (world, chunk) for world, chunk in all_tasks}

        for future in as_completed(futures):
            world_name, world_items_data = future.result()
            if not world_items_data:
                failed_worlds.add(world_name)
                continue

            succeeded_worlds.add(world_name)

            sales_history_batch = []
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

            if sales_history_batch:
                cursor.executemany("""
                INSERT OR IGNORE INTO sales_history (item_id, world_name, timestamp, price_per_unit, quantity, hq, buyer_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, sales_history_batch)
                total_sales_inserted += len(sales_history_batch)

    conn.commit()
    print(f"=== Fetch Summary: Succeeded {len(succeeded_worlds)} worlds, Failed {len(failed_worlds)} worlds ===")
    if failed_worlds:
        print(f"⚠️ Failed Worlds: {', '.join(sorted(failed_worlds))}")
    print(f"=== Sales History Updated: {total_sales_inserted:,} transactions saved ===")

    # Purge old sales history (> 7 days)
    seven_days_ago = int(now_dt.timestamp()) - (7 * 86400)
    cursor.execute("DELETE FROM sales_history WHERE timestamp < ?", (seven_days_ago,))

    # Pool cleanup: remove items with no sales if DB has enough data
    cursor.execute("SELECT COUNT(*) FROM sales_history WHERE timestamp >= ?", (seven_days_ago,))
    recent_sales_total = cursor.fetchone()[0]
    if recent_sales_total > 500:
        cursor.execute("""
        DELETE FROM items_pool 
        WHERE item_id NOT IN (
            SELECT DISTINCT item_id FROM sales_history WHERE timestamp >= ?
        )
        """, (seven_days_ago,))

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
