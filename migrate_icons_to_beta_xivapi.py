"""
全アイテムのアイコンURLを beta.xivapi.com に統一更新するスクリプト。
Garland Tools v3 API からアイコンコードを取得し、beta.xivapi.com のURL形式で
icons_map.json、items_metadata (DB)、data.json を一括更新する。
"""
import requests, json, sqlite3, os, time
from datetime import datetime, timezone

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def icon_code_to_beta_url(icon_raw):
    """Garland API の icon フィールドから beta.xivapi.com のURLを生成"""
    code_str = str(icon_raw).replace("t/", "")
    code_int = int(code_str)
    code_padded = f"{code_int:06d}"
    folder = code_padded[:3] + "000"
    return f"https://beta.xivapi.com/api/1/asset/ui/icon/{folder}/{code_padded}_hr1.tex?format=png"

# DB接続
conn = sqlite3.connect('data/market_data.db', timeout=60)
c = conn.cursor()
c.execute('PRAGMA busy_timeout=60000;')

# 全アイテムIDを取得
c.execute('SELECT item_id FROM items_pool')
pool_ids = [r[0] for r in c.fetchall()]
print(f"Processing {len(pool_ids)} items from items_pool...")

icons_map = {}
now_str = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
batch = []
resolved = 0
errors = 0

for iid in pool_ids:
    try:
        url = f"https://www.garlandtools.org/db/doc/item/ja/3/{iid}.json"
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            r.encoding = 'utf-8'
            item = r.json().get('item', {})
            name = item.get('name', f'アイテム #{iid}')
            icon_raw = item.get('icon')
            category = item.get('categoryName', '一般')
            
            if icon_raw:
                icon_url = icon_code_to_beta_url(icon_raw)
                icons_map[str(iid)] = icon_url
                batch.append((iid, name, icon_url, category, now_str))
                resolved += 1
            else:
                print(f"  WARNING: No icon field for item {iid} ({name})")
        else:
            print(f"  WARNING: Garland API returned HTTP {r.status_code} for item {iid}")
        time.sleep(0.05)
    except Exception as e:
        errors += 1
        print(f"  ERROR for item {iid}: {e}")

print(f"\nResolved: {resolved} | Errors: {errors}")

# DB更新
c.executemany(
    'INSERT OR REPLACE INTO items_metadata (item_id, item_name, icon_url, category_name, fetched_at) VALUES (?, ?, ?, ?, ?)',
    batch
)
conn.commit()
print(f"Updated {len(batch)} items in items_metadata.")

# icons_map.json 保存
with open('docs/icons_map.json', 'w', encoding='utf-8') as f:
    json.dump(icons_map, f, ensure_ascii=False, indent=2)
print(f"Saved {len(icons_map)} entries to docs/icons_map.json.")

# data.json を再出力
import main
main.export_web_json(conn, 'docs/data.json')
conn.close()

print("\nDONE! All icon URLs now use beta.xivapi.com.")
