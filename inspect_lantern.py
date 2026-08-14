import requests, json

with open('docs/data.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

for wname, items in d.get('data', {}).items():
    for item in items:
        if 'アンティーク・ランタン' in item.get('item_name', ''):
            iid = item.get('item_id')
            print(f"Dashboard Item Name: {item.get('item_name')} | Item ID: {iid}")
            print(f"Current Icon URL in data.json: {item.get('icon_url')}")
            
            url = f"https://www.garlandtools.org/db/doc/item/ja/3/{iid}.json"
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                g_data = res.json().get('item', {})
                icon_code = g_data.get('icon')
                print(f"Garland v3 Exact Item Name: \"{g_data.get('name')}\" | Exact Icon Code: {icon_code}")
                
                if icon_code:
                    str_clean = str(icon_code).replace('t/', '')
                    c_int = int(str_clean)
                    str_6 = f"{c_int:06d}"
                    folder_6 = str_6[:3] + "000"
                    correct_url = f"https://xivapi.com/i/{folder_6}/{str_6}.png"
                    print(f"Calculated Correct Icon URL: {correct_url}")
                    st = requests.head(correct_url, headers=headers, timeout=3).status_code
                    print(f"Correct Icon URL Status: {st}")
            break
    break
