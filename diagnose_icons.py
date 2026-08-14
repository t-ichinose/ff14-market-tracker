import requests, json, time

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

problem_ids = [52288, 52289, 51962]

for iid in problem_ids:
    url = f"https://www.garlandtools.org/db/doc/item/ja/3/{iid}.json"
    r = requests.get(url, headers=headers, timeout=5)
    item = r.json().get('item', {})
    name = item.get('name', '???')
    icon_raw = item.get('icon')
    
    print(f"=== {name} (ID:{iid}, icon_raw:{repr(icon_raw)}) ===")
    
    code_str = str(icon_raw).replace("t/", "")
    code_int = int(code_str)
    code_padded = f"{code_int:06d}"
    folder = code_padded[:3] + "000"
    
    # Try many URL patterns
    test_urls = [
        ("XIVAPI classic", f"https://xivapi.com/i/{folder}/{code_padded}.png"),
        ("XIVAPI hr1", f"https://xivapi.com/i/{folder}/{code_padded}_hr1.png"),
        ("Beta XIVAPI tex", f"https://beta.xivapi.com/api/1/asset/ui/icon/{folder}/{code_padded}_hr1.tex?format=png"),
        ("Garland item icon", f"https://garlandtools.org/db/icons/item/{icon_raw}.png"),
        ("Garland no-t", f"https://garlandtools.org/db/icons/item/{code_str}.png"),
        ("Garland files", f"https://garlandtools.org/files/icons/item/{icon_raw}.png"),
    ]
    
    for label, tu in test_urls:
        try:
            r2 = requests.head(tu, headers=headers, timeout=5, allow_redirects=True)
            marker = "<<< OK" if r2.status_code == 200 else ""
            print(f"  [{label}] {tu} -> HTTP {r2.status_code} {marker}")
        except Exception as e:
            print(f"  [{label}] {tu} -> ERROR {e}")
    
    print()

# Now check a WORKING item for comparison
print("=== COMPARISON: Working item (コスモプレデター認証鍵, known good) ===")
working_ids = [49826, 13114, 43961]
for iid in working_ids:
    url = f"https://www.garlandtools.org/db/doc/item/ja/3/{iid}.json"
    r = requests.get(url, headers=headers, timeout=5)
    item = r.json().get('item', {})
    name = item.get('name', '???')
    icon_raw = item.get('icon')
    
    code_str = str(icon_raw).replace("t/", "")
    code_int = int(code_str)
    code_padded = f"{code_int:06d}"
    folder = code_padded[:3] + "000"
    
    xivapi_url = f"https://xivapi.com/i/{folder}/{code_padded}.png"
    r2 = requests.head(xivapi_url, headers=headers, timeout=3)
    
    has_t = "t/" in str(icon_raw)
    print(f"  {name} (ID:{iid}) icon_raw:{repr(icon_raw)} has_t_prefix:{has_t} XIVAPI:{r2.status_code}")
