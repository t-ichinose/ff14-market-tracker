import re

local = open('docs/index.html','r',encoding='utf-8').read()
github = open('docs/index_github.html','r',encoding='utf-8').read()

print(f'GitHub版: {len(github)} bytes, {github.count(chr(10))} lines')
print(f'ローカル版: {len(local)} bytes, {local.count(chr(10))} lines')
print()

# world-grid CSS比較
for label, html in [('GitHub', github), ('Local', local)]:
    m = re.search(r'\.world-grid\s*\{([^}]+)\}', html)
    if m:
        print(f'{label} .world-grid CSS:')
        print(f'  {m.group(1).strip()[:300]}')
        print()
    m = re.search(r'\.world-column\s*\{([^}]+)\}', html)
    if m:
        print(f'{label} .world-column CSS:')
        print(f'  {m.group(1).strip()[:300]}')
        print()

# renderWorldGrid関数の違い
for label, html in [('GitHub', github), ('Local', local)]:
    m = re.search(r'function renderWorldGrid\(\)\s*\{', html)
    if m:
        start = m.start()
        # Extract first 500 chars of the function
        snippet = html[start:start+500]
        print(f'{label} renderWorldGrid start:')
        print(f'  {snippet[:300]}...')
        print()

# img要素のパターン確認
for label, html in [('GitHub', github), ('Local', local)]:
    imgs = re.findall(r'img[^>]*class="item-icon"[^>]*', html)
    if imgs:
        print(f'{label} item-icon img pattern: {imgs[0][:150]}')
    else:
        # テンプレートリテラル内のimgを検索
        imgs = re.findall(r'item-icon.*?src=.*?(?=\>)', html)
        if imgs:
            print(f'{label} item-icon pattern: {imgs[0][:150]}')
        else:
            print(f'{label} item-icon: not found in static HTML (generated via JS)')
