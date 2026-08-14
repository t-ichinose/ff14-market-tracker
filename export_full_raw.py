import sqlite3
import csv
import os
import requests
import json
import shutil
from datetime import datetime, timezone, timedelta

output_dir = 'check_data'
os.makedirs(output_dir, exist_ok=True)

conn = sqlite3.connect('data/market_data.db')
c = conn.cursor()

c.execute('SELECT item_id, item_name FROM items_metadata')
meta_dict = {row[0]: row[1] for row in c.fetchall()}

CITY_MAP = {
    1: 'リムサ・ロミンサ', 2: 'ウルダハ', 3: 'グリダニア',
    4: 'イシュガルド', 7: 'クガネ', 10: 'クリスタリウム',
    12: 'オールド・シャーレアン', 14: 'トライヨラ'
}

# ==========================================
# ① 取引データ (全項目生データ)
# ==========================================
path_1 = os.path.join(output_dir, '1_trade_history_full_raw.csv')
path_1_jp = os.path.join(output_dir, '1_取引データ_全項目生データ.csv')

c.execute('SELECT item_id, world_name, timestamp, price_per_unit, quantity, hq, buyer_name FROM sales_history ORDER BY timestamp DESC LIMIT 50000')
rows_1 = c.fetchall()

with open(path_1, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.writer(f)
    writer.writerow([
        'アイテムID', '日本語アイテム名', 'ワールド名',
        'UNIXタイムスタンプ', '取引日時(JST)', '単価(Gil)',
        '数量', '合計金額(Gil)', 'HQフラグ', '購入者名'
    ])
    for r in rows_1:
        iid, wname, ts, price, qty, hq, buyer = r
        item_name = meta_dict.get(iid, f'アイテム #{iid}')
        jst_time = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S') if ts else ''
        writer.writerow([
            iid, item_name, wname,
            ts, jst_time, price,
            qty, price * qty, 'HQ' if hq else 'NQ', buyer
        ])

shutil.copy(path_1, path_1_jp)
print(f'Exported full trade history to {path_1} ({len(rows_1)} rows)')

# ==========================================
# ② 出品データ (全項目生データ - Universalis APIから取得可能な全プロパティ)
# ==========================================
path_2 = os.path.join(output_dir, '2_active_listings_full_raw.csv')
path_2_jp = os.path.join(output_dir, '2_出品データ_全項目生データ.csv')

sample_ids = [row[0] for row in c.execute('SELECT item_id FROM items_pool LIMIT 20').fetchall()]
headers = {'User-Agent': 'FFXIV-Market-Tracker/1.0'}

full_listings = []
for iid in sample_ids[:10]:
    try:
        url = f'https://universalis.app/api/v2/Chocobo/{iid}'
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            listings = data.get('listings', [])
            item_name = meta_dict.get(iid, f'アイテム #{iid}')
            for l in listings:
                c_id = l.get('retainerCity')
                city_name = CITY_MAP.get(c_id, f'都市ID:{c_id}')
                materia_str = json.dumps(l.get('materia', []), ensure_ascii=False) if l.get('materia') else 'なし'
                full_listings.append([
                    iid, item_name, 'Chocobo',
                    l.get('pricePerUnit'), l.get('quantity'), l.get('total'),
                    'HQ' if l.get('hq') else 'NQ',
                    l.get('retainerName', ''), city_name,
                    l.get('retainerID', ''), l.get('sellerID', ''),
                    l.get('stainID', 0), 'はい' if l.get('onMannequin') else 'いいえ',
                    materia_str, l.get('lastReviewTime', 0)
                ])
    except Exception as e:
        print(f"Error fetching listings for {iid}: {e}")

with open(path_2, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.writer(f)
    writer.writerow([
        'アイテムID', '日本語アイテム名', 'ワールド名',
        '出品単価(Gil)', '出品数量', '合計価格(Gil)',
        'HQフラグ', 'リテイナー名', '出品都市',
        'リテイナーID', 'セラーID',
        '染色ID', 'マネキン出品',
        '装着マテリア情報', '最終確認タイムスタンプ'
    ])
    writer.writerows(full_listings)

shutil.copy(path_2, path_2_jp)
print(f'Exported full active listings to {path_2} ({len(full_listings)} rows)')
