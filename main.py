import sqlite3
import requests
import json
import os
import sys
import time
import gzip
import threading
from datetime import datetime, timezone, timedelta
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

    # Prune sales history older than 7 days
    seven_days_ago_ts = int(time.time()) - (7 * 86400)
    cursor.execute("DELETE FROM sales_history WHERE timestamp < ?", (seven_days_ago_ts,))

    conn.commit()
    return conn

def _load_json_int_key_map(path):
    """Load a JSON file and return a dict with integer keys."""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
                return {int(k): v for k, v in d.items() if str(k).isdigit()}
        except Exception:
            pass
    return {}

def get_items_search():
    return _load_json_int_key_map("docs/items_search.json")

def get_icons_map():
    return _load_json_int_key_map("docs/icons_map.json")

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

_thread_local = threading.local()

def get_thread_session():
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)
        _thread_local.session = session
    return _thread_local.session

def fetch_single_dc_data(dc_name, target_ids):
    session = get_thread_session()
    ids_str = ",".join(map(str, target_ids))
    detail_url = f"https://universalis.app/api/v2/history/{dc_name}/{ids_str}?entriesWithin=604800&entriesToReturn=2000"
    for attempt in range(3):
        try:
            time.sleep(0.25)  # Politeness delay between requests
            d_res = session.get(detail_url, timeout=(5.0, 15.0))
            if d_res.status_code == 200:
                data = d_res.json()
                if "items" in data:
                    return dc_name, data["items"]
                elif "itemID" in data:
                    return dc_name, {str(data["itemID"]): data}
                return dc_name, {}
            print(f"[WARNING] [{dc_name}] API HTTP {d_res.status_code}. Retrying ({attempt + 1}/3)...", flush=True)
            time.sleep(1.0 * (2 ** attempt))
        except Exception as e:
            print(f"[WARNING] [{dc_name}] Network Error ({e}). Retrying ({attempt + 1}/3)...", flush=True)
            time.sleep(1.0 * (2 ** attempt))
    print(f"[API ERROR] Failed to fetch chunk for DC {dc_name} after 3 attempts.", flush=True)
    return dc_name, {}

def export_web_json(conn, output_path="docs/data.json.gz"):
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

    # Always use fixed 7.0 days for 1-week daily velocity calculation
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
        if len(hist_list) < 20:
            item_hist = {
                "price": price,
                "qty": qty,
                "hq": bool(hq),
                "ts": ts
            }
            if buyer:
                item_hist["buyer"] = buyer
            hist_list.append(item_hist)

    # 1. Compute Global Median & Noise Bounds for each item_id across all 32 worlds
    global_bounds_by_item = {}
    item_all_prices = {}

    for (iid, wname), items_list in sales_by_item_world.items():
        for x in items_list:
            if x["price"] > 0:
                item_all_prices.setdefault(iid, []).append(x["price"])

    for iid, all_prices in item_all_prices.items():
        if not all_prices:
            continue
        sorted_p = sorted(all_prices)
        g_med = sorted_p[len(sorted_p) // 2]

        # Upper bound (RMT / Gil Transfer Filter)
        if g_med <= 1_000:
            upper_bound = max(10_000.0, 20.0 * g_med)
        elif g_med <= 100_000:
            upper_bound = 10.0 * g_med
        else:
            upper_bound = 5.0 * g_med

        # Lower bound (Outlier filter: exclude sales below 30% of global median)
        lower_bound = max(10.0, 0.30 * g_med)

        global_bounds_by_item[iid] = (lower_bound, upper_bound, g_med)

    # Pre-compute JST timezone constants once (outside the per-item loop)
    jst = timezone(timedelta(hours=9))
    now_jst = now_dt.astimezone(jst)
    today_date_jst = now_jst.date()
    start_date_jst = today_date_jst - timedelta(days=7)
    start_midnight_dt = datetime(start_date_jst.year, start_date_jst.month, start_date_jst.day, tzinfo=jst)
    start_midnight_ts = int(start_midnight_dt.timestamp())

    days_labels = [(today_date_jst - timedelta(days=i)).strftime("%m/%d") for i in range(7, -1, -1)]

    # Pre-compute day boundary timestamps for numeric comparison (much faster than strftime per-tx)
    day_boundaries = []
    for i in range(7, -1, -1):
        d = today_date_jst - timedelta(days=i)
        d_start = int(datetime(d.year, d.month, d.day, tzinfo=jst).timestamp())
        d_end = d_start + 86400
        day_boundaries.append((days_labels[7 - i], d_start, d_end))

    # Group calculated metrics by world
    data_by_world = {}

    for (iid, wname), items_list in sales_by_item_world.items():
        if not items_list:
            continue

        lower_bound, upper_bound, g_med = global_bounds_by_item.get(iid, (1.0, 300_000_000.0, 1000.0))

        # Global Cross-World Noise Filter: Exclude 1G dump sales and RMT/Gil transfers
        clean_items = [x for x in items_list if lower_bound <= x["price"] <= upper_bound]
        
        # Also clean history list for modal display
        hist_raw = history_by_item_world.get((iid, wname), [])
        clean_hist = [h for h in hist_raw if lower_bound <= h["price"] <= upper_bound][:20]

        if not clean_items:
            # If all transactions in this world were RMT/outliers, treat world as having 0 valid sales
            clean_prices = []
            total_qty = 0
            trade_cnt = 0
            real_vel = 0.0
            min_p = 0
            max_p = 0
            avg_p = 0
            valid_items = []
        else:
            valid_items = clean_items
            clean_prices = [x["price"] for x in valid_items]
            total_qty = sum(x["qty"] for x in valid_items)
            trade_cnt = len(valid_items)
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

        # Filter out transaction logs before JST midnight of 7 days ago
        valid_items = [x for x in valid_items if x["ts"] >= start_midnight_ts]
        
        # Calculate daily weighted average trends using pre-computed day boundaries (numeric comparison)
        daily_trend = []
        valid_avgs = []
        for d_lbl, d_start_ts, d_end_ts in day_boundaries:
            day_txs = [x for x in valid_items if d_start_ts <= x["ts"] < d_end_ts]
            if day_txs:
                d_qty = sum(x["qty"] for x in day_txs)
                d_rev = sum(x["price"] * x["qty"] for x in day_txs)
                d_wavg = round(d_rev / float(d_qty)) if d_qty > 0 else 0
                daily_trend.append({"date": d_lbl, "weighted_avg": d_wavg, "volume": d_qty})
                if d_wavg > 0:
                    valid_avgs.append(d_wavg)
            else:
                daily_trend.append({"date": d_lbl, "weighted_avg": 0, "volume": 0})

        trend_pct = 0.0
        # Intuitive Trend: Compare Latest Active Day's Avg (latest_p) vs 7-Day Baseline Avg (avg_p)
        if valid_avgs and avg_p > 0:
            latest_p = valid_avgs[-1]
            trend_pct = round(((latest_p - avg_p) / float(avg_p)) * 100.0, 1)

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
            "daily_trend": daily_trend,
            "trend_pct": trend_pct,
            "history": clean_hist,
            "updated_at": now_str
        }

        data_by_world.setdefault(wname, []).append(item_obj)

    # Sort items per world by sale_velocity DESC
    for wname in data_by_world:
        data_by_world[wname].sort(key=lambda x: x["sale_velocity"], reverse=True)

    # Load existing docs/data.json.gz or docs/data.json if present, to preserve data for non-updated DCs
    merged_data_by_world = {}
    for check_file in ["docs/data.json.gz", "docs/data.json"]:
        if os.path.exists(check_file):
            try:
                if check_file.endswith(".gz"):
                    with gzip.open(check_file, "rt", encoding="utf-8") as f:
                        existing_json = json.load(f)
                else:
                    with open(check_file, "r", encoding="utf-8") as f:
                        existing_json = json.load(f)
                if existing_json and "data" in existing_json:
                    merged_data_by_world = existing_json.get("data", {})
                    break
            except Exception as e:
                print(f"Notice: Could not load existing {check_file} for merging: {e}")

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

    json_bytes = json.dumps(web_data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    # Export compressed web JSON
    gz_output_path = output_path if output_path.endswith(".gz") else output_path + ".gz"
    tmp_gz_path = gz_output_path + ".tmp"
    with gzip.open(tmp_gz_path, "wb", compresslevel=9) as f:
        f.write(json_bytes)
    os.replace(tmp_gz_path, gz_output_path)

    # Remove uncompressed raw data file if present to prevent accidental 100MB+ commits
    raw_output_path = output_path.replace(".gz", "") if output_path.endswith(".gz") else output_path
    if raw_output_path != gz_output_path and os.path.exists(raw_output_path):
        try:
            os.remove(raw_output_path)
        except Exception:
            pass

    gz_size_kb = os.path.getsize(gz_output_path) / 1024
    raw_size_kb = len(json_bytes) / 1024
    print(f"Successfully exported web JSON to {gz_output_path} ({gz_size_kb:.0f} KB, compressed from {raw_size_kb:.0f} KB)", flush=True)

def fetch_and_save_all(target_dc=None):
    now_dt = datetime.now(timezone.utc)
    now_str = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = init_db("data/market_data.db")
    cursor = conn.cursor()

    dcs = [target_dc] if target_dc and target_dc in JP_DATACENTERS else JP_DATACENTERS

    recent_ids_all = set()
    for dc in dcs:
        recent_url = f"https://universalis.app/api/v2/extra/stats/recently-updated?dcName={dc}"
        try:
            res = requests.get(recent_url, headers=DEFAULT_HEADERS, timeout=10)
            if res.ok:
                ids = res.json().get('items', [])[:50]
                recent_ids_all.update(ids)
        except Exception as e:
            print(f"[{dc}] Error fetching recent items: {e}", flush=True)

    cursor.execute("SELECT item_id FROM items_pool WHERE item_id >= 100")
    existing_pool_ids = [row[0] for row in cursor.fetchall()]
    if not existing_pool_ids:
        items_search = get_items_search()
        existing_pool_ids = [iid for iid in items_search.keys() if iid >= 100]
    recent_ids_all.update(existing_pool_ids)



    if recent_ids_all:
        pool_batch = [(iid, now_str) for iid in recent_ids_all]
        cursor.executemany("INSERT OR IGNORE INTO items_pool (item_id, added_at) VALUES (?, ?)", pool_batch)
    conn.commit()

    target_ids = list(recent_ids_all)

    chunk_size = 50
    item_chunks = [target_ids[i:i + chunk_size] for i in range(0, len(target_ids), chunk_size)]
    all_tasks = [(dc, chunk) for chunk in item_chunks for dc in dcs]

    print(f"=== Bulk Fetching {len(target_ids)} items ({len(all_tasks)} DC tasks) across {len(dcs)} DCs ({','.join(dcs)}) ===", flush=True)

    total_sales_inserted = 0
    failed_dcs = set()
    succeeded_dcs = set()

    completed_count = 0
    total_tasks = len(all_tasks)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_single_dc_data, dc, chunk): (dc, chunk) for dc, chunk in all_tasks}

        for future in as_completed(futures):
            completed_count += 1
            dc_name, items_data = future.result()
            if completed_count % 5 == 0 or completed_count == total_tasks:
                print(f"Progress: {completed_count}/{total_tasks} tasks completed ({(completed_count/total_tasks)*100:.0f}%)", flush=True)

            if not items_data:
                failed_dcs.add(dc_name)
                continue

            succeeded_dcs.add(dc_name)

            sales_history_batch = []
            for item_id_str, data in items_data.items():
                item_id = int(item_id_str)
                entries = data.get("entries", []) or data.get("recentHistory", [])
                for h in entries:
                    ts = h.get("timestamp", 0)
                    price = h.get("pricePerUnit", 0)
                    qty = h.get("quantity", 0)
                    hq = 1 if h.get("hq") else 0
                    buyer = h.get("buyerName", "")
                    world_name = h.get("worldName", "")
                    if ts > 0 and price > 0 and world_name:
                        sales_history_batch.append((item_id, world_name, ts, price, qty, hq, buyer))

            if sales_history_batch:
                cursor.executemany("""
                INSERT OR IGNORE INTO sales_history (item_id, world_name, timestamp, price_per_unit, quantity, hq, buyer_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, sales_history_batch)
                total_sales_inserted += len(sales_history_batch)

    conn.commit()
    print(f"=== Fetch Summary: Succeeded {len(succeeded_dcs)} DCs, Failed {len(failed_dcs)} DCs ===", flush=True)
    if failed_dcs:
        print(f"⚠️ Failed DCs: {', '.join(sorted(failed_dcs))}", flush=True)
    print(f"=== Sales History Updated: {total_sales_inserted:,} transactions saved ===", flush=True)


    # Purge old sales history (> 7 days retention)
    seven_days_ago_ts = int(now_dt.timestamp()) - (7 * 86400)
    cursor.execute("DELETE FROM sales_history WHERE timestamp < ?", (seven_days_ago_ts,))
    cursor.execute("PRAGMA optimize;")

    # Pool cleanup: remove items with no sales if DB has enough data
    cursor.execute("SELECT COUNT(*) FROM sales_history WHERE timestamp >= ?", (seven_days_ago_ts,))
    recent_sales_total = cursor.fetchone()[0]
    if recent_sales_total > 500:
        cursor.execute("""
        DELETE FROM items_pool 
        WHERE item_id NOT IN (
            SELECT DISTINCT item_id FROM sales_history WHERE timestamp >= ?
        )
        """, (seven_days_ago_ts,))

    conn.commit()

    cursor.execute("SELECT DISTINCT item_id FROM items_pool")
    all_pool_ids = [row[0] for row in cursor.fetchall()]
    if all_pool_ids:
        resolve_item_metadata_batch(conn, all_pool_ids)

    export_web_json(conn, "docs/data.json.gz")
    conn.close()

if __name__ == "__main__":
    target_dc = None
    if len(sys.argv) > 1 and sys.argv[1] == "--dc":
        target_dc = sys.argv[2] if len(sys.argv) > 2 else "Mana"
    fetch_and_save_all(target_dc)
