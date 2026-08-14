# -*- coding: utf-8 -*-
import sys
import requests
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding='utf-8')
JST = timezone(timedelta(hours=9))

def print_history_markdown(world, item_id, item_name):
    url = f'https://universalis.app/api/v2/{world}/{item_id}?entriesToReturn=5'
    res = requests.get(url)
    if res.status_code == 200:
        history = res.json().get('recentHistory', [])
        print(f"### 【{world} ワールド】アイテム: {item_name} (ID: {item_id})")
        print("| 取引成立日時 (JST) | 売却単価 | 数量 | 品質 | 合計金額 | 購入者プレイヤー名 |")
        print("|---|---|---|---|---|---|")
        for h in history:
            ts = h.get('timestamp', 0)
            dt_jst = datetime.fromtimestamp(ts, tz=JST).strftime('%Y-%m-%d %H:%M:%S') if ts else '-'
            hq_str = 'HQ' if h.get('hq') else 'NQ'
            price = h.get('pricePerUnit', 0)
            qty = h.get('quantity', 0)
            total = h.get('total', price * qty)
            buyer = h.get('buyerName', '匿名')
            print(f"| {dt_jst} | {price:,} G | {qty} 個 | {hq_str} | {total:,} G | {buyer} |")
        print()

print_history_markdown('Chocobo', 33916, 'ダークマターG8')
print_history_markdown('Asura', 41780, '美輝鉱')
print_history_markdown('Anima', 19884, '魔導の薬茶')
