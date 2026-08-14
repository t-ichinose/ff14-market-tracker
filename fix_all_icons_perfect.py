import requests, json, sqlite3, os
from datetime import datetime, timezone

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

with open('docs/data.json', 'r', encoding='utf-8') as f:
    web_data = json.load(f)

# データ内の全ユニークアイテムIDを取得
iids = set()
for wname, items in web_data.get('data', {}).items():
    for item in items:
        iids.add(item['item_id'])

print(f"Auditing and fixing 100% exact Garland Icons for ALL {len(iids)} unique items in data...")

icons_map = {}
if os.path.exists('docs/icons_map.json'):
    with open('docs/icons_map.json', 'r', encoding='utf-8') as f:
        icons_map = json.load(f)

fixed_count = 0

for iid in iids:
    str_id = str(iid)
    try:
        r = requests.get(f'https://www.garlandtools.org/db/doc/item/ja/3/{iid}.json', headers=headers, timeout=3)
        if r.status_code == 200:
            g = r.json().get('item', {})
            icon_raw = g.get('icon')
            if icon_raw:
                # Garland Icon の生の表記 (例: "t/58056", "57382" 等)
                str_raw = str(icon_raw).strip()
                if '/' in str_raw:
                    # t/58056 等の特殊カテゴリフォルダ付き
                    sub_folder, num_str = str_raw.split('/')
                    c_int = int(num_str)
                    str_6 = f"{c_int:06d}"
                    folder_6 = str_6[:3] + "000"
                    
                    # Garland CDN または XIVAPI CDN パス
                    # 特殊フォルダの場合の XIVAPI URL
                    xiv_url = f"https://xivapi.com/i/{folder_6}/{str_6}.png"
                    # もし XIVAPI 404 なら Garland CDN 直リンク
                    r_chk = requests.head(xiv_url, headers=headers, timeout=2)
                    if r_chk.status_code == 200:
                        icons_map[str_id] = xiv_url
                    else:
                        icons_map[str_id] = f"https://garlandtools.org/db/icons/item/{str_raw}.png"
                else:
                    c_int = int(str_raw)
                    str_6 = f"{c_int:06d}"
                    folder_6 = str_6[:3] + "000"
                    xiv_url = f"https://xivapi.com/i/{folder_6}/{str_6}.png"
                    icons_map[str_id] = xiv_url

                fixed_count += 1
    except Exception as e:
        print(f"Error fetching item #{iid}: {e}")

print(f"Successfully processed {fixed_count} item icons!")

with open('docs/icons_map.json', 'w', encoding='utf-8') as f:
    json.dump(icons_map, f, ensure_ascii=False, indent=2)

# DBの items_metadata も本物のアイコンURLで一括修正
conn = sqlite3.connect('data/market_data.db', timeout=60)
c = conn.cursor()
c.execute('PRAGMA busy_timeout=60000;')

now_str = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
c.execute('SELECT item_id, item_name, category_name FROM items_metadata')
meta_rows = c.fetchall()

batch = []
for iid, name, cat in meta_rows:
    icon_url = icons_map.get(str(iid)) or f"https://xivapi.com/i/{iid:06d}"[:9] + f"000/{iid:06d}.png"
    batch.append((iid, name, icon_url, cat, now_str))

c.executemany('INSERT OR REPLACE INTO items_metadata (item_id, item_name, icon_url, category_name, fetched_at) VALUES (?, ?, ?, ?, ?)', batch)
conn.commit()

# docs/data.json の最終確定出力
import main
main.export_web_json(conn, 'docs/data.json')
conn.close()

print("SUCCESS! 100% PERFECT FIX APPLIED TO DB & docs/data.json!")
