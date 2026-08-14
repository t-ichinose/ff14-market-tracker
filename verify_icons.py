import json, requests

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

with open('docs/data.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

problem_ids = {51272, 50415, 52288, 52278, 51262, 51263, 52289, 51964, 51965, 51963, 51251, 51962, 50297, 52615, 52613}

seen = {}
for wname, items in d.get('data', {}).items():
    for item in items:
        iid = item.get('item_id')
        if iid in problem_ids and iid not in seen:
            seen[iid] = item

print(f"Found {len(seen)} of {len(problem_ids)} problem items in current data.json")
print()

ok = 0
fail = 0
for iid, item in seen.items():
    url = item.get('icon_url', '')
    uses_beta = 'beta.xivapi.com' in url
    try:
        r = requests.head(url, headers=headers, timeout=5, allow_redirects=True)
        status = r.status_code
    except Exception as e:
        status = f"ERR:{e}"
    
    marker = "OK" if status == 200 else "FAIL"
    if status == 200:
        ok += 1
    else:
        fail += 1
    name = item.get("item_name", "")
    print(f"  [{marker}] ID:{iid} | {name} | beta:{uses_beta} | HTTP:{status}")

print(f"\nResult: {ok} OK / {fail} FAIL")
