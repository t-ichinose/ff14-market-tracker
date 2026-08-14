# -*- coding: utf-8 -*-
import json

d = json.load(open('docs/data.json', 'r', encoding='utf-8'))
all_items = {}
for dc, items in d.get('data', {}).items():
    for item in items:
        iid = item.get('item_id')
        name = item.get('item_name', '')
        cat = item.get('meta', {}).get('category', '')
        all_items[iid] = (name, cat)

print("Unique Items in data.json:", len(all_items))
print("\n--- Items with Item ID <= 20 or category=='クリスタル' or '触媒' ---")
for iid, (name, cat) in sorted(all_items.items()):
    if iid <= 20 or cat in ['クリスタル', '触媒'] or any(k in name for k in ['シャード', 'クリスタル', 'クラスター', '触媒']):
        print(f"ID: {iid:<6} | Category: {cat:<10} | Name: {name}")
