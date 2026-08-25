/**
 * FF14 Market Tracker - Automated Test Suite
 * Run with: node test_suite.js
 */

const fs = require('fs');
const assert = require('assert');

console.log("=========================================");
console.log("  FF14 Market Tracker Test Suite");
console.log("=========================================\n");

const html = fs.readFileSync('docs/index.html', 'utf8');

// Extract script block
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (!scriptMatch) {
  console.error("❌ ERROR: Could not find <script> block in docs/index.html");
  process.exit(1);
}

const jsCode = scriptMatch[1];

// 1. Syntax Check
try {
  new Function(jsCode);
  console.log("✅ Test 1: JavaScript Syntax Compilation Check PASS");
} catch (e) {
  console.error("❌ Test 1 FAIL: Syntax Error:", e.message);
  process.exit(1);
}

// Create a sandbox execution scope
const sandboxFn = new Function('exports', 'window', 'document', 'localStorage', 'navigator', 'fetch', 'setTimeout', 'clearTimeout', jsCode + '; return { getComputedIconUrl, isCrystalItem, formatTimeLocal, escapeHtml, getOrComputeDailyTrend, buildTrendBadgeHtml, findDcForWorld, dcWorldsMap };');

const mockLocalStorage = {
  getItem: () => null,
  setItem: () => {}
};
const mockDocument = {
  getElementById: () => null,
  querySelectorAll: () => [],
  activeElement: null,
  hidden: false,
  addEventListener: () => {}
};
const mockWindow = {
  location: { hostname: 'localhost' },
  addEventListener: () => {}
};

let scope;
try {
  scope = sandboxFn({}, mockWindow, mockDocument, mockLocalStorage, { clipboard: {} }, () => Promise.resolve(), setTimeout, clearTimeout);
  console.log("✅ Test 2: Sandbox Initializer Scope PASS");
} catch (e) {
  console.error("❌ Test 2 FAIL: Scope Initialization Error:", e.message);
  process.exit(1);
}

// 2. Icon URL Calculation Logic Test
try {
  const iconUrl1 = scope.getComputedIconUrl(2);
  const iconUrl2 = scope.getComputedIconUrl(35000);
  assert.strictEqual(iconUrl1, 'https://v2.xivapi.com/api/asset?path=ui/icon/000000/000002_hr1.tex&format=png');
  assert.strictEqual(iconUrl2, 'https://v2.xivapi.com/api/asset?path=ui/icon/035000/035000_hr1.tex&format=png');
  assert.ok(scope.getComputedIconUrl(null).includes('021001_hr1.tex'));
  console.log("✅ Test 3: getComputedIconUrl (XIVAPI v2 Path Resolver) PASS");
} catch (e) {
  console.error("❌ Test 3 FAIL:", e.message);
  process.exit(1);
}

// 3. Crystal Filter Logic Test
try {
  assert.strictEqual(scope.isCrystalItem(2), true);
  assert.strictEqual(scope.isCrystalItem({ item_id: 19 }), true);
  assert.strictEqual(scope.isCrystalItem({ item_id: 100, item_name: 'ファイアクリスタル' }), true);
  assert.strictEqual(scope.isCrystalItem({ item_id: 500, meta: { category: 'クリスタル' } }), true);
  assert.strictEqual(scope.isCrystalItem({ item_id: 25000, item_name: '鉄鉱' }), false);
  console.log("✅ Test 4: isCrystalItem Edge Cases PASS");
} catch (e) {
  console.error("❌ Test 4 FAIL:", e.message);
  process.exit(1);
}

// 4. HTML Escaping Test (XSS Security)
try {
  const escaped = scope.escapeHtml('<script>alert("xss")</script>');
  assert.strictEqual(escaped, '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;');
  console.log("✅ Test 5: escapeHtml (XSS Sanitizer) PASS");
} catch (e) {
  console.error("❌ Test 5 FAIL:", e.message);
  process.exit(1);
}

// 5. Date Formatting Edge Cases
try {
  assert.strictEqual(scope.formatTimeLocal(null), '-');
  assert.ok(scope.formatTimeLocal('2026-08-25T12:00:00Z').includes('2026-08-25'));
  console.log("✅ Test 6: formatTimeLocal Null/Edge Cases PASS");
} catch (e) {
  console.error("❌ Test 6 FAIL:", e.message);
  process.exit(1);
}

// 6. World to DC Resolver Test
try {
  assert.strictEqual(scope.findDcForWorld('Chocobo'), 'Mana');
  assert.strictEqual(scope.findDcForWorld('Tonberry'), 'Elemental');
  assert.strictEqual(scope.findDcForWorld('Bahamut'), 'Gaia');
  assert.strictEqual(scope.findDcForWorld('Shinryu'), 'Meteor');
  assert.strictEqual(scope.findDcForWorld('UnknownWorld'), null);
  console.log("✅ Test 7: findDcForWorld (All 32 Worlds Resolver) PASS");
} catch (e) {
  console.error("❌ Test 7 FAIL:", e.message);
  process.exit(1);
}

// 7. Daily Trend Metric Computation & 0-Division Guard Test
try {
  const emptyTrend = scope.getOrComputeDailyTrend(null);
  assert.deepStrictEqual(emptyTrend.trend, []);
  assert.strictEqual(emptyTrend.trendPct, 0);

  const mockItem = {
    history: [
      { ts: Math.floor(Date.now() / 1000) - 86400, price: 1000, qty: 2 },
      { ts: Math.floor(Date.now() / 1000), price: 1500, qty: 1 }
    ]
  };
  const computedTrend = scope.getOrComputeDailyTrend(mockItem);
  assert.strictEqual(computedTrend.trend.length, 7);
  assert.ok(!isNaN(computedTrend.trendPct));
  console.log("✅ Test 8: getOrComputeDailyTrend Zero-Division & Bounds Guard PASS");
} catch (e) {
  console.error("❌ Test 8 FAIL:", e.message);
  process.exit(1);
}

console.log("\n=========================================");
console.log(" 🎉 ALL 8 AUTOMATED TESTS PASSED CLEANLY!");
console.log("=========================================");
