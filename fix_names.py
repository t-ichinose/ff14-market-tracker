import sqlite3, json, csv, os, shutil

output_dir = 'check_data'
conn = sqlite3.connect('data/market_data.db', timeout=60)
c = conn.cursor()
c.execute('PRAGMA busy_timeout=60000;')

# docs/items_search.json から全16,843件の正確な日本語名をロード
with open('docs/items_search.json', 'r', encoding='utf-8') as f:
    search_dict = json.load(f)

c.execute('SELECT item_id FROM items_pool')
pool_ids = [r[0] for r in c.fetchall()]

batch = []
for iid in pool_ids:
    str_id = str(iid)
    name = search_dict.get(str_id) or f"アイテム #{iid}"
    batch.append((iid, name, "", "一般", "2026-08-07"))

c.executemany('INSERT OR REPLACE INTO items_metadata (item_id, item_name, icon_url, category_name, fetched_at) VALUES (?, ?, ?, ?, ?)', batch)
conn.commit()

# メタデータ辞書の再取得
c.execute('SELECT item_id, item_name, category_name FROM items_metadata')
meta_dict = {row[0]: (row[1], row[2]) for row in c.fetchall()}

c.execute('SELECT item_id, added_at FROM items_pool ORDER BY item_id ASC')
pool_rows = c.fetchall()

csv_path = os.path.join(output_dir, 'items_pool_registered.csv')
csv_path_jp = os.path.join(output_dir, '単発取得後_アイテムプール登録一覧.csv')

fallback_count = 0
with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.writer(f)
    writer.writerow(['アイテムID', '日本語アイテム名', 'カテゴリ名', 'プール登録日時'])
    for r in pool_rows:
        iid, added_at = r
        item_name, cat = meta_dict.get(iid, (f'アイテム #{iid}', '一般'))
        if item_name.startswith('アイテム #'):
            fallback_count += 1
        writer.writerow([iid, item_name, cat, added_at])

shutil.copy(csv_path, csv_path_jp)
print(f'SUCCESS! Re-exported clean CSV. Fallback "アイテム #..." count is NOW EXACTLY: {fallback_count} items!')
