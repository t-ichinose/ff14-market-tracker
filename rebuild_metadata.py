"""Rebuild items_metadata from items_search.json (no external API calls)."""
import sqlite3
import json
import os
import time
from datetime import datetime, timezone

db_path = "data/market_data.db"
conn = sqlite3.connect(db_path, timeout=60)
cursor = conn.cursor()
cursor.execute("PRAGMA journal_mode=WAL;")

# Load items_search.json (already valid UTF-8)
with open("docs/items_search.json", "r", encoding="utf-8") as f:
    items_search = json.load(f)

print(f"Loaded {len(items_search)} item names from items_search.json")

# Get all item IDs we need metadata for
ids = [r[0] for r in cursor.execute('SELECT DISTINCT item_id FROM item_market_stats').fetchall()]
print(f"Need metadata for {len(ids)} items in market stats")

# Clear and rebuild
cursor.execute('DELETE FROM items_metadata')
conn.commit()

now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
inserted = 0
for iid in ids:
    name = items_search.get(str(iid), f"アイテム #{iid}")
    cursor.execute(
        "INSERT OR REPLACE INTO items_metadata (item_id, item_name, icon_url, category_name, fetched_at) VALUES (?, ?, ?, ?, ?)",
        (iid, name, "", "一般", now_str)
    )
    inserted += 1

conn.commit()
print(f"Inserted {inserted} items into items_metadata")

# Verify
count = cursor.execute('SELECT count(*) FROM items_metadata').fetchone()[0]
print(f"items_metadata row count: {count}")

# Sample check
samples = cursor.execute('SELECT item_id, item_name FROM items_metadata LIMIT 5').fetchall()
with open("check_names.txt", "w", encoding="utf-8") as f:
    for r in samples:
        f.write(f"{r[0]}: {r[1]}\n")
print("Wrote sample to check_names.txt")

# Now export data.json
import main
main.export_web_json(conn, "docs/data.json")

# Final verification
data = json.load(open("docs/data.json", "r", encoding="utf-8"))
chocobo = data["data"].get("Chocobo", [])
with open("check_names.txt", "w", encoding="utf-8") as f:
    for item in chocobo[:10]:
        f.write(f"{item['item_id']}: {item['item_name']} (vel={item['history_7d']['sale_velocity']})\n")
print(f"Final verification: {len(data['data'])} worlds, {sum(len(v) for v in data['data'].values())} total items")

conn.close()
