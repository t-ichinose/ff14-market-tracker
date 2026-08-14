import json
import re

local_html = open('docs/index.html', 'r', encoding='utf-8').read()
github_html = open('docs/index_github.html', 'r', encoding='utf-8').read()

local_data = json.load(open('docs/data.json', 'r', encoding='utf-8'))

print("=" * 60)
print("  【GitHub公開版 (旧)】 vs 【現在のローカル版 (新)】 詳細比較分析")
print("=" * 60)

print("\n1. 画面レイアウト・表示単位の基本構造の違い:")
print("  [GitHub公開版 (旧)]")
print("    - 画面に並ぶカラム数 : 4 カラム (DC単位: Elemental, Gaia, Mana, Meteor)")
print("    - 表示データ単位      : DC全体での集計数値 (各DCにつき 1セット)")
print("    - 各DCのカード枚数    : 約 76 ~ 110 枚")
print("    - 画面全体の総カード数 : 4 DC × 約90枚 ＝ 約 360 枚")

print("\n  [現在のローカル版 (新)]")
print("    - 画面に並ぶカラム数 : 8 カラム (ワールド単位: Anima, Asura, Chocobo, Hades, Ixion, Masamune, Pandaemonium, Titan)")
print("    - 表示データ単位      : 選択中DC内の全8ワールドごとの個別数値")
print("    - 各ワールドのカード数: 110 枚")
print("    - 画面全体の総カード数 : 8 ワールド × 110枚 ＝ 880 枚  (★ 旧版の 2.4倍以上のDOM要素数！)")

print("\n2. JavaScript レンダリング時の計算処理の違い (Mana DC 110アイテムの場合):")
print("  [GitHub公開版 (旧)]")
print("    - DCごとのアイテム配列をそのまま sort して HTML化するだけ")
print("    - 計算ループ回数: 4 DC × 90 アイテム ＝ 約 360 回のループ")
print("\n  [現在のローカル版 (新)]")
print("    - 110個のアイテムそれぞれの中に含まれる 32ワールド分の辞書データ (item.worlds[worldName]) を探索")
print("    - 8ワールドそれぞれに対して 110アイテムのオブジェクト再生成 + 並び替え + HTML文字列生成")
print("    - 計算ループ回数: 8 ワールド × 110 アイテム ＝ 880 回のオブジェクト生成 & メトリクス計算")

print("\n3. 画像 (アイコン) と DOM 要素数の違い:")
print("  [GitHub公開版 (旧)]")
print("    - 生成されるカード要素: 約 360 個")
print("  [現在のローカル版 (新)]")
print("    - 生成されるカード要素: 880 個  (各カード内にヘッダー、バッジ2種、サブ指標2種、過去取引帯、グラフボタンあり)")
print("    - DOMノード総数: 約 10,000 個以上のHTMLノードを一括構築")

print("\n4. DC切り替え時の挙動の違い:")
print("  [GitHub公開版 (旧)]")
print("    - ページ読み込み時に 4 DC すべてのデータを一括レンダリング済み。")
print("    - DCタブを押した時は、CSSの `scrollIntoView()` または非表示切替だけで瞬時に移動 (再レンダリング 0ms！)")
print("  [現在のローカル版 (新)]")
print("    - DCタブ（Elemental / Gaia / Mana / Meteor）を押すたびに、切り替え先のDCデータで 8 ワールド × 110 カード (880枚) を1から全消去・全再構築 (innerHTML) している！")

print("=" * 60)
