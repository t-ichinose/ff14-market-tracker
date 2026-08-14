import sqlite3, requests, csv, io, json, os
from datetime import datetime, timezone

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

print("Downloading XIVAPI Item.csv for exact icon codes...")
text = requests.get('https://raw.githubusercontent.com/xivapi/ffxiv-datamining/master/csv/ja/Item.csv', headers=headers, timeout=15).content.decode('utf-8')
reader = csv.reader(io.StringIO(text))
next(reader)
next(reader)

icon_map = {}
name_map = {}

for r in reader:
    if len(r) > 11 and r[0].isdigit():
        iid = int(r[0])
        name = r[1].strip()
        icon_code = r[11].strip()
        if name:
            name_map[iid] = name
        if icon_code.isdigit():
            c_int = int(icon_code)
            folder = f"{c_int:06d}"[:3] + "000"
            icon_url = f"https://xivapi.com/i/{folder}/{c_int:06d}.png"
            icon_map[iid] = icon_url

conn = sqlite3.connect('data/market_data.db', timeout=60)
c = conn.cursor()
c.execute('PRAGMA busy_timeout=60000;')

c.execute('SELECT item_id FROM items_pool')
pool_ids = [r[0] for r in c.fetchall()]

now_str = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

batch = []
for iid in pool_ids:
    name = name_map.get(iid) or f"アイテム #{iid}"
    icon_url = icon_map.get(iid) or "https://xivapi.com/i/020000/021001.png"
    batch.append((iid, name, icon_url, '一般', now_str))

c.executemany('''
INSERT OR REPLACE INTO items_metadata (item_id, item_name, icon_url, category_name, fetched_at)
VALUES (?, ?, ?, ?, ?)
''', batch)

conn.commit()

import main
main.export_web_json(conn, 'docs/data.json')
conn.close()

print(f"SUCCESS! Updated high-res icons for ALL {len(batch)} pooled items in DB and exported docs/data.json!")
