import json

data = json.load(open('docs/data.json', 'r', encoding='utf-8'))

with open('vel_debug.txt', 'w', encoding='utf-8') as f:
    for w in ['Anima', 'Asura', 'Chocobo', 'Hades']:
        items = data['data'].get(w, [])
        for it in items[:5]:
            name = it.get('item_name', '?')
            vel = it['history_7d']['sale_velocity']
            f.write(f"{w}: {name} -> vel={vel}\n")
        f.write("---\n")

    # Also check: how many distinct velocity values exist
    all_vels = set()
    for w, items in data['data'].items():
        for it in items:
            all_vels.add(it['history_7d']['sale_velocity'])
    f.write(f"\nDistinct velocity values: {len(all_vels)}\n")
    f.write(f"Sample: {sorted(list(all_vels))[:30]}\n")

    # Check チャイ・トゥ・ヴヌー across all worlds
    f.write("\n--- チャイ・トゥ・ヴヌー across worlds ---\n")
    for w, items in data['data'].items():
        for it in items:
            if 'チャイ' in it.get('item_name', ''):
                f.write(f"{w}: vel={it['history_7d']['sale_velocity']}\n")
                break
