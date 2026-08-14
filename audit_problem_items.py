import requests, json

with open('docs/data.json', 'r', encoding='utf-8') as f:
    web_data = json.load(f)

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

target_names = ['スコップ', 'カーウェン・チュニック', 'エバーキープ・モニター', 'アンティーク・ランタン']

print('=== Auditing problem items with Garland v3 API ===')
checked = set()

for wname, items in web_data.get('data', {}).items():
    for item in items:
        name = item.get('item_name', '')
        iid = item.get('item_id')
        if any(t in name for t in target_names) and iid not in checked:
            checked.add(iid)
            url = f'https://www.garlandtools.org/db/doc/item/ja/3/{iid}.json'
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code == 200:
                g = r.json().get('item', {})
                exact_name = g.get('name')
                icon_code = g.get('icon')
                print(f'Item ID {iid} -> Name: "{exact_name}" | Garland Icon: {icon_code}')
                if icon_code:
                    str_code = f'{int(icon_code):06d}'
                    folder = str_code[:3] + '000'
                    xiv_url = f'https://xivapi.com/i/{folder}/{str_code}.png'
                    xiv_hr = f'https://xivapi.com/i/{folder}/{str_code}_hr1.png'
                    print(f'  Normal URL ({xiv_url}): Status {requests.head(xiv_url, timeout=3).status_code}')
                    print(f'  HD URL     ({xiv_hr}): Status {requests.head(xiv_hr, timeout=3).status_code}')
