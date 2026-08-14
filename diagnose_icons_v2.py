import requests, json, time

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# 404だった15アイテム
error_ids = [51272, 50415, 52288, 52278, 51262, 51263, 52289, 51964, 51965, 51963, 51251, 51962, 50297, 52615, 52613]

# 正常だったアイテムからサンプル
ok_ids = [49826, 13114, 13115, 43961, 47336, 49240]

print("=" * 80)
print("ERROR ITEMS (404 on xivapi.com)")
print("=" * 80)

for iid in error_ids:
    url = f"https://www.garlandtools.org/db/doc/item/ja/3/{iid}.json"
    r = requests.get(url, headers=headers, timeout=5)
    item = r.json().get('item', {})
    name = item.get('name', '???')
    icon_raw = item.get('icon')
    has_t = str(icon_raw).startswith("t/")
    
    code_str = str(icon_raw).replace("t/", "")
    code_int = int(code_str)
    code_padded = f"{code_int:06d}"
    folder = code_padded[:3] + "000"
    
    # Try beta.xivapi.com (new XIVAPI v2)
    beta_url = f"https://beta.xivapi.com/api/1/asset/ui/icon/{folder}/{code_padded}_hr1.tex?format=png"
    try:
        r2 = requests.head(beta_url, headers=headers, timeout=5, allow_redirects=True)
        beta_status = r2.status_code
    except:
        beta_status = "ERR"
    
    print(f"  ID:{iid:6d} | {name:30s} | icon_raw:{str(icon_raw):12s} | t_prefix:{has_t} | beta_xivapi:{beta_status}")
    time.sleep(0.1)

print()
print("=" * 80)
print("WORKING ITEMS (200 on xivapi.com)")
print("=" * 80)

for iid in ok_ids:
    url = f"https://www.garlandtools.org/db/doc/item/ja/3/{iid}.json"
    r = requests.get(url, headers=headers, timeout=5)
    item = r.json().get('item', {})
    name = item.get('name', '???')
    icon_raw = item.get('icon')
    has_t = str(icon_raw).startswith("t/")
    print(f"  ID:{iid:6d} | {name:30s} | icon_raw:{str(icon_raw):12s} | t_prefix:{has_t}")
    time.sleep(0.1)
