import requests
import sys

sys.stdout.reconfigure(encoding='utf-8')

def test_market_scan(scope_name: str = "Mana", top_n: int = 10):
    print(f"[{scope_name}] スコープでリアルタイム市場データを取得中...\n")

    # Step 1: 直近で更新されたアイテムIDを取得
    recent_url = "https://universalis.app/api/v2/extra/stats/recently-updated"
    try:
        res = requests.get(recent_url, timeout=10)
        res.raise_for_status()
        recent_items = res.json().get('items', [])[:50]
    except Exception as e:
        print(f"エラー: 直近更新アイテムの取得に失敗しました ({e})")
        return

    if not recent_items:
        print("アクティブなアイテムが見つかりませんでした。")
        return

    # Step 2: Universalis APIで詳細データ取得
    ids_str = ",".join(map(str, recent_items))
    detail_url = f"https://universalis.app/api/v2/{scope_name}/{ids_str}"
    
    # dailySaleVelocity等の統計情報を計算させるため entries: 5 を設定
    params = {"listings": 1, "entries": 5}
    
    try:
        detail_res = requests.get(detail_url, params=params, timeout=10)
        detail_res.raise_for_status()
        items_data = detail_res.json().get('items', {})
    except Exception as e:
        print(f"エラー: マーケット詳細データの取得に失敗しました ({e})")
        return

    # Step 3: 販売速度でソート
    parsed_list = []
    for item_id, data in items_data.items():
        velocity = data.get("dailySaleVelocity") or 0.0
        parsed_list.append({
            "item_id": int(item_id),
            "velocity": float(velocity),
            "min_price": data.get("minPrice", 0)
        })
    
    parsed_list.sort(key=lambda x: x["velocity"], reverse=True)
    top_items = parsed_list[:top_n]

    # Step 4: XIVAPIで日本語名取得
    print("アイテムIDを日本語名称に変換中...")
    top_ids_str = ",".join(str(x["item_id"]) for x in top_items)
    xivapi_url = f"https://xivapi.com/Item?ids={top_ids_str}&columns=ID,Name_ja&language=ja"
    
    name_map = {}
    try:
        xiv_res = requests.get(xivapi_url, timeout=10)
        if xiv_res.status_code == 200:
            results = xiv_res.json().get("Results", [])
            for item in results:
                if isinstance(item, dict) and "ID" in item:
                    name_map[item["ID"]] = item.get("Name_ja", "Unknown")
    except Exception as e:
        print(f"※アイテム名の変換中の警告: {e}")

    # Step 5: 表示
    print("\n" + "="*80)
    print(f"   【{scope_name} DC】 リアルタイム高流動性マーケットアイテム TOP {top_n}")
    print("="*80)
    print(f"{'順位':<4} | {'アイテム名 (ID)':<34} | {'1日平均販売数':<14} | {'最安値':<12}")
    print("-" * 80)

    for rank, item in enumerate(top_items, 1):
        i_id = item["item_id"]
        item_name = name_map.get(i_id, f"Unknown (ID:{i_id})")
        
        name_with_id = f"{item_name} ({i_id})"
        if len(name_with_id) > 24:
            display_name = name_with_id[:22] + ".."
        else:
            display_name = name_with_id
            
        velocity_str = f"{item['velocity']:.1f} 個/日"
        price_str = f"{item['min_price']:,} Gil"
        
        print(f"{rank:<4} | {display_name:<34} | {velocity_str:<14} | {price_str:<12}")
    
    print("="*80)

if __name__ == "__main__":
    test_market_scan(scope_name="Mana", top_n=10)
