import requests
import time

def test_chunk_fetch():
    recent_url = "https://universalis.app/api/v2/extra/stats/recently-updated"
    recent_items = requests.get(recent_url, timeout=10).json().get('items', [])[:20]

    print("Testing 10 items chunk...")
    chunk_1 = recent_items[:10]
    ids_str = ",".join(map(str, chunk_1))
    
    start_time = time.time()
    url = f"https://universalis.app/api/v2/Mana/{ids_str}?listings=1&entries=5"
    res = requests.get(url, timeout=10)
    elapsed = time.time() - start_time
    
    print(f"Status: {res.status_code}, Elapsed: {elapsed:.2f} seconds")
    if res.status_code == 200:
        print("Success! Items fetched:", len(res.json().get('items', {})))

if __name__ == "__main__":
    test_chunk_fetch()
