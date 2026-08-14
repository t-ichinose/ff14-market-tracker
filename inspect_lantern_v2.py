import requests, json

with open('docs/data.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

found = False
for wname, items in d.get('data', {}).items():
    for item in items:
        name = item.get('item_name', '')
        if 'ランタン' in name or 'アンティーク' in name or 'スコップ' in name or 'チュニック' in name:
            iid = item.get('item_id')
            print(f"Item: {name} (ID #{iid}) | Current IconURL: {item.get('icon_url')}")
            
            url = f"https://www.garlandtools.org/db/doc/item/ja/3/{iid}.json"
            try:
                res = requests.get(url, headers=headers, timeout=3)
                if res.status_code == 200:
                    g_data = res.json().get('item', {})
                    exact_name = g_data.get('name')
                    icon_code = g_data.get('icon')
                    print(f"  -> Garland v3 Exact Name: \"{exact_name}\" | Icon Code: {icon_code}")
                    if icon_code:
                        clean_code = str(icon_code).replace('t/', '')
                        c_int = int(clean_code)
                        str_6 = f"{c_int:06d}"
                        folder_6 = str_6[:3] + "000"
                        correct_url = f"https://xivapi.com/i/{folder_6}/{str_6}.png"
                        st = requests.head(correct_url, headers=headers, timeout=3).status_code
                        print(f"  -> Correct Icon URL: {correct_url} (HTTP Status: {st})")
            except Exception as e:
                print(f"  -> Error: {e}")
