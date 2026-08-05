import requests
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

def test_scope():
    recent_url = "https://universalis.app/api/v2/extra/stats/recently-updated"
    recent_items = requests.get(recent_url, timeout=10).json().get('items', [])[:5]
    ids_str = ",".join(map(str, recent_items))

    print(f"Testing Item IDs: {ids_str}\n")

    for scope in ["Chocobo", "Mana", "Japan"]:
        url = f"https://universalis.app/api/v2/{scope}/{ids_str}"
        res = requests.get(url, timeout=10).json()
        items = res.get('items', {})
        print(f"=== Scope: {scope} ===")
        for i_id, info in items.items():
            print(f"ID {i_id}: dailySaleVelocity={info.get('dailySaleVelocity')}, minPrice={info.get('minPrice')}, avgPrice={info.get('averagePrice')}")

if __name__ == "__main__":
    test_scope()
