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
    cursor.execute("PRAGMA busy_timeout=60000;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    
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
        PRIMARY KEY (item_id, world_name, timestamp, price_per_unit, quantity, hq, buyer_name)
    )
    """)
    
    # 2b. sales_history 高速検索用インデックス (#5)
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_sales_item_world ON sales_history (item_id, world_name)
    """)
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_sales_timestamp ON sales_history (timestamp)
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
            print(f"[Cleanup] Removed {deleted_count:,} trade records older than {days} days.")
    except Exception as e:
        print(f"[Cleanup] Error cleaning up old logs: {e}")

DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# キャッシュ用グローバル変数 (#7: ファイルの重複ロード防止)
_items_search_cache = None
_icons_map_cache = None

def get_items_search():
    """items_search.json を一度だけ読み込んでキャッシュ返却"""
    global _items_search_cache
    if _items_search_cache is None:
        _items_search_cache = load_items_search()
    return _items_search_cache

def get_icons_map():
    """icons_map.json を一度だけ読み込んでキャッシュ返却"""
    global _icons_map_cache
    if _icons_map_cache is None:
        _icons_map_cache = {}
        if os.path.exists("docs/icons_map.json"):
            try:
                with open("docs/icons_map.json", "r", encoding="utf-8") as f:
                    _icons_map_cache = json.load(f)
            except Exception:
                pass
    return _icons_map_cache

def ensure_items_search_json(output_path="docs/items_search.json"):
    if os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
        return
    print("Building docs/items_search.json index (16,843 marketable items)...")
    try:
        import csv, io
        headers = DEFAULT_HEADERS
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
    headers = DEFAULT_HEADERS
    meta_map = {}
    
    items_search = get_items_search()
    icons_map = get_icons_map()
    cursor = conn.cursor()

    missing_ids = []
    for iid in item_ids:
        cursor.execute("SELECT item_name, icon_url, category_name FROM items_metadata WHERE item_id = ?", (iid,))
        row = cursor.fetchone()
        if row and row[0] and not row[0].startswith("アイテム #") and len(row[0]) < 60 and row[1] and "021001_hr1" not in row[1]:
            meta_map[iid] = {"name": row[0], "icon": row[1], "category": row[2]}
        else:
            missing_ids.append(iid)

    if not missing_ids:
        return meta_map

    print(f"Resolving exact item names for {len(missing_ids)} items...")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for iid in missing_ids:
        name = items_search.get(str(iid)) or items_search.get(iid) or f"アイテム #{iid}"
        icon_url = icons_map.get(str(iid)) or icons_map.get(iid) or ""
        category_name = "一般"

        # Direct v2.xivapi.com Sheet API fallback for 100% accurate icons (Patch 1.0 to 7.x)
        if not icon_url:
            try:
                res = requests.get(f"https://v2.xivapi.com/api/sheet/Item/{iid}?fields=Icon", headers=headers, timeout=4)
                if res.status_code == 200:
                    icon_data = res.json().get("fields", {}).get("Icon", {})
                    path_hr1 = icon_data.get("path_hr1")
                    if path_hr1:
                        icon_url = f"https://v2.xivapi.com/api/asset?path={path_hr1}&format=png"
            except Exception:
                pass

        # Garland API fallback for category and fallback name
        try:
            res = requests.get(f"https://www.garlandtools.org/db/doc/item/ja/3/{iid}.json", headers=headers, timeout=3)
            if res.status_code == 200:
                res.encoding = 'utf-8'
                g_data = res.json().get("item", {})
                if not name or name.startswith("アイテム #"):
                    g_name = g_data.get("name")
                    if g_name:
                        name = g_name
                category_name = g_data.get("category_name", category_name)
        except Exception:
            pass

        if not icon_url:
            icon_url = "https://v2.xivapi.com/api/asset?path=ui/icon/020000/021001_hr1.tex&format=png"

        cursor.execute("""
        INSERT OR REPLACE INTO items_metadata (item_id, item_name, icon_url, category_name, fetched_at)
        VALUES (?, ?, ?, ?, ?)
        """, (iid, name, icon_url, category_name, now_str))

        meta_map[iid] = {"name": name, "icon": icon_url, "category": category_name}

    conn.commit()
    return meta_map

def fetch_single_world_data(world_name, target_ids):
    """1ワールド分のアイテムデータを取得。指数バックオフでリトライ (#17)"""
    headers = DEFAULT_HEADERS
    ids_str = ",".join(map(str, target_ids))
    detail_url = f"https://universalis.app/api/v2/{world_name}/{ids_str}?entries=50"
    for attempt in range(3):
        try:
            d_res = requests.get(detail_url, headers=headers, timeout=8)
            if d_res.status_code == 200:
                return world_name, d_res.json().get('items', {})
            elif d_res.status_code == 429:
                # レート制限: Retry-After ヘッダーを尊重、なければ指数バックオフ
                retry_after = int(d_res.headers.get('Retry-After', 2 ** (attempt + 1)))
                time.sleep(min(retry_after, 30))
            elif d_res.status_code in (502, 503, 504):
                time.sleep(2 ** attempt)  # 1s → 2s → 4s
        except Exception:
            time.sleep(2 ** attempt)
    return world_name, {}

def process_dc_pipeline(scope_name: str, conn, now_str: str = None):
    """1つのDCに属する全ワールドのデータを取得・保存 (#6: connを外部から受け取る)"""
    if not now_str:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    headers = DEFAULT_HEADERS
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

    # ① プールシート (items_pool) に追加登録 (全DC共通・重複排除ルール)
    # 取引履歴 (sales_history) およびクリスタル類 (ID: 2-19) も全自動でプールへ確実に同期
    cursor.execute("INSERT OR IGNORE INTO items_pool (item_id, added_at) SELECT DISTINCT item_id, ? FROM sales_history", (now_str,))
    crystal_batch = [(cid, now_str) for cid in range(2, 20)]
    cursor.executemany("INSERT OR IGNORE INTO items_pool (item_id, added_at) VALUES (?, ?)", crystal_batch)
    conn.commit()

    if recent_items:
        cursor.execute("SELECT item_id FROM items_pool")
        existing_ids = set(row[0] for row in cursor.fetchall())
        new_items = [iid for iid in set(recent_items) if iid not in existing_ids]
        
        if new_items:
            pool_batch = [(iid, now_str) for iid in new_items]
            cursor.executemany("INSERT OR IGNORE INTO items_pool (item_id, added_at) VALUES (?, ?)", pool_batch)
            conn.commit()
            print(f"  [{scope_name}] Added {len(new_items)} new unique items to shared pool.")

    # ② プールに入っている全アイテムIDを取得
    cursor.execute("SELECT item_id FROM items_pool")
    target_ids = [row[0] for row in cursor.fetchall()]
    if not target_ids:
        conn.close()
        return

    print(f"  [Iterative Pipeline] Fetching {len(target_worlds)} worlds for {len(target_ids)} pooled items (entries=50)...")

    # ③ 50アイテムずつの「取得 ➔ メモリ変換 ➔ executemany 保存 ➔ commit」小刻みサイクル
    chunk_size = 50
    item_chunks = [target_ids[i:i + chunk_size] for i in range(0, len(target_ids), chunk_size)]

    total_sales_inserted = 0
    total_stats_inserted = 0

    for chunk_idx, chunk_ids in enumerate(item_chunks, 1):
        world_results = {}
        with ThreadPoolExecutor(max_workers=len(target_worlds)) as executor:
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

            dc_name = WORLD_TO_DC.get(world_name, scope_name)

            for item_id_str, data in world_items_data.items():
                item_id = int(item_id_str)

                # 取引履歴のメモリ蓄積 (最大50件)
                recent_history = data.get("recentHistory", [])[:50]
                for h in recent_history:
                    ts = h.get("timestamp", 0)
                    price = h.get("pricePerUnit", 0)
                    qty = h.get("quantity", 0)
                    hq = 1 if h.get("hq") else 0
                    buyer = h.get("buyerName", "")
                    if ts > 0 and price > 0:
                        sales_history_batch.append((item_id, world_name, ts, price, qty, hq, buyer))

                # 統計情報のメモリ蓄積
                market_stats_batch.append((
                    item_id, world_name, dc_name, now_str,
                    data.get("minPrice", 0), data.get("minPriceNQ", 0), data.get("minPriceHQ", 0),
                    data.get("averagePrice", 0.0), data.get("averagePriceNQ", 0.0), data.get("averagePriceHQ", 0.0),
                    data.get("currentAveragePrice", 0.0), data.get("currentAveragePriceNQ", 0.0), data.get("currentAveragePriceHQ", 0.0),
                    data.get("maxPrice", 0), data.get("maxPriceNQ", 0), data.get("maxPriceHQ", 0),
                    data.get("unitsForSale", 0), data.get("listingsCount", 0),
                    data.get("unitsSold", 0), data.get("recentHistoryCount", 0),
                    data.get("regularSaleVelocity", 0.0), data.get("nqSaleVelocity", 0.0), data.get("hqSaleVelocity", 0.0)
                ))

        # 小刻みサイクル: executemany ➔ commit (メモリ消費わずか数MB)
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

    print(f"  [{scope_name}] Complete Iterative Cycle Finished: {total_sales_inserted:,} sales & {total_stats_inserted:,} stats saved.")

def export_web_json(conn, output_path="docs/data.json"):
    """DB データを集約して docs/data.json を出力 (#6: connは必須引数に)"""
    cursor = conn.cursor()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    items_search = get_items_search()
    icons_map = get_icons_map()

    cursor.execute("SELECT item_id, item_name, icon_url, category_name FROM items_metadata")
    meta_dict = {row[0]: {"name": row[1], "icon": row[2], "category": row[3]} for row in cursor.fetchall()}

    # 実際のデータ蓄積日数を算出して正確な日販数を計算 (#8)
    cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM sales_history")
    ts_range = cursor.fetchone()
    if ts_range and ts_range[0] and ts_range[1]:
        actual_days = max(1.0, (ts_range[1] - ts_range[0]) / 86400.0)
    else:
        actual_days = 7.0

    cursor.execute("""
    SELECT item_id, world_name, SUM(quantity) as total_qty, COUNT(*) as trade_count
    FROM sales_history
    GROUP BY item_id, world_name
    """)
    velocity_calc = {(row[0], row[1]): round(row[2] / actual_days, 1) for row in cursor.fetchall()}

    # トリム平均 (Trimmed Mean): 上下10%の異常値・外れ値をカットして真の平均単価を算出
    cursor.execute("SELECT item_id, world_name, price_per_unit FROM sales_history")
    sales_raw = {}
    for row in cursor.fetchall():
        sales_raw.setdefault((row[0], row[1]), []).append(row[2])

    sales_stats = {}
    for key, prices in sales_raw.items():
        min_p = min(prices)
        max_p = max(prices)
        
        # 5件以上あれば上下10%をカットしたトリム平均、少なければ中央値(メディアン)
        if len(prices) >= 5:
            sp = sorted(prices)
            cut = max(1, int(len(sp) * 0.10))
            trimmed = sp[cut: len(sp) - cut] if (len(sp) - 2 * cut) > 0 else sp
            avg_p = round(sum(trimmed) / float(len(trimmed)))
        else:
            sp = sorted(prices)
            avg_p = sp[len(sp) // 2]
            
        count_p = len(prices)
        sales_stats[key] = (min_p, avg_p, max_p, count_p)

    cursor.execute("""
    SELECT item_id, world_name, dc_name, min_price, avg_price, max_price, units_for_sale, listings_count, sale_velocity, updated_at
    FROM item_market_stats
    """)
    rows = cursor.fetchall()

    data_by_world = {}
    for r in rows:
        iid, wname, dcname, min_p, avg_p, max_p, u_sale, l_count, vel, updated = r
        meta = meta_dict.get(iid, {})
        item_name = meta.get("name")
        if not item_name or item_name.startswith("アイテム #"):
            item_name = items_search.get(str(iid)) or items_search.get(iid) or f"アイテム #{iid}"
        
        mapped_icon = icons_map.get(str(iid)) or icons_map.get(iid)
        icon_url = meta.get("icon", "")
        if mapped_icon:
            icon_url = mapped_icon
        
        if "beta.xivapi.com/api/1/asset/ui/icon/" in icon_url:
            icon_url = icon_url.replace("https://beta.xivapi.com/api/1/asset/ui/icon/", "https://xivapi.com/i/").replace(".tex?format=png", ".png")

        if not icon_url or "000000.png" in icon_url or "021001_hr1" in icon_url:
            icon_url = "https://xivapi.com/i/020000/021001_hr1.png"
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
        
        # 案1クリーン判定: 平均価格が最高値の35%以上ある本物の高額流通品のみ抽出(資金移動ノイズを永久排除)
        clean_high_value_items = [
            x for x in items 
            if x.get("max_price", 0) > 0 and ((x.get("avg_price", 0) / float(x["max_price"])) >= 0.35)
        ]
        top_by_max_price = set(x["item_id"] for x in sorted(clean_high_value_items, key=lambda x: x.get("max_price", 0), reverse=True)[:60])
        
        top_by_revenue = set(x["item_id"] for x in sorted(filtered_items, key=lambda x: x["daily_revenue"], reverse=True)[:60])
        top_by_velocity = set(x["item_id"] for x in sorted(filtered_items, key=lambda x: x["sale_velocity"], reverse=True)[:60])
        crystal_ids = set(x["item_id"] for x in items if 2 <= x["item_id"] <= 19)
        
        keep_ids = top_by_revenue.union(top_by_velocity).union(top_by_max_price).union(crystal_ids)
        combined_items = [x for x in items if x["item_id"] in keep_ids]
        
        final_data_by_world[wname] = combined_items

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
    """メインエントリポイント: データ取得 → クリーンアップ → メタデータ解決 → JSON出力 (#6: DB接続を一元化)"""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dcs = [target_dc] if target_dc and target_dc in JP_DATACENTERS else JP_DATACENTERS

    conn = init_db("data/market_data.db")

    for scope in dcs:
        print(f"--- Processing DC & All Worlds Direct: {scope} ---")
        try:
            process_dc_pipeline(scope, conn, now_str)
        except Exception as e:
            print(f"[{scope}] Error in pipeline: {e}")

    cleanup_old_logs(conn, 7)

    # メタデータ解決: プール内全アイテムの名前・アイコン・カテゴリをDBに書き込む (#1)
    cursor = conn.cursor()
    cursor.execute("SELECT item_id FROM items_pool")
    all_pool_ids = [row[0] for row in cursor.fetchall()]
    if all_pool_ids:
        print(f"Resolving metadata for {len(all_pool_ids)} pooled items...")
        resolve_item_metadata_batch(conn, all_pool_ids)

    export_web_json(conn, "docs/data.json")
    conn.close()

if __name__ == "__main__":
    target_dc = None
    if len(sys.argv) > 1 and sys.argv[1] == "--dc":
        target_dc = sys.argv[2] if len(sys.argv) > 2 else "Mana"
    fetch_and_save_all(target_dc)
