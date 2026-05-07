/**
 * Tests for lib/dedup.js
 * Run with: node --test test/dedup.test.js
 */

const { test, describe } = require("node:test");
const assert = require("node:assert/strict");

describe("MessageDeduplicator", () => {
  test("first call for (jid, ts) returns false (not duplicate)", () => {
    const { MessageDeduplicator } = require("../lib/dedup");
    const dedup = new MessageDeduplicator(60);
    assert.strictEqual(dedup.isDuplicate("aaa@s.whatsapp.net", 1000), false);
  });

  test("second call for same (jid, ts) returns true (duplicate)", () => {
    const { MessageDeduplicator } = require("../lib/dedup");
    const dedup = new MessageDeduplicator(60);
    dedup.isDuplicate("aaa@s.whatsapp.net", 1000);
    assert.strictEqual(dedup.isDuplicate("aaa@s.whatsapp.net", 1000), true);
  });

  test("different ts for same jid is not a duplicate", () => {
    const { MessageDeduplicator } = require("../lib/dedup");
    const dedup = new MessageDeduplicator(60);
    dedup.isDuplicate("aaa@s.whatsapp.net", 1000);
    assert.strictEqual(dedup.isDuplicate("aaa@s.whatsapp.net", 2000), false);
  });

  test("same ts but different jid is not a duplicate", () => {
    const { MessageDeduplicator } = require("../lib/dedup");
    const dedup = new MessageDeduplicator(60);
    dedup.isDuplicate("aaa@s.whatsapp.net", 1000);
    assert.strictEqual(dedup.isDuplicate("bbb@s.whatsapp.net", 1000), false);
  });

  test("entry expires after window seconds", () => {
    const { MessageDeduplicator } = require("../lib/dedup");
    const windowSec = 60;
    const dedup = new MessageDeduplicator(windowSec);
    const nowSec = Math.floor(Date.now() / 1000);

    // Record at nowSec
    dedup.isDuplicate("aaa@s.whatsapp.net", nowSec);

    // Simulate old entry by checking with a ts that is windowSec+1 in the past
    const oldTs = nowSec - (windowSec + 1);
    // Directly add an old entry to simulate expiry
    dedup._store.set("aaa@s.whatsapp.net", new Map([[oldTs, oldTs]]));

    // Old entry should not be seen as duplicate; new check cleans it
    assert.strictEqual(dedup.isDuplicate("aaa@s.whatsapp.net", oldTs), false);
  });

  test("prune removes entries older than window", () => {
    const { MessageDeduplicator } = require("../lib/dedup");
    const dedup = new MessageDeduplicator(60);
    const nowSec = Math.floor(Date.now() / 1000);
    const oldTs = nowSec - 120;

    // Manually inject old entry
    dedup._store.set("aaa@s.whatsapp.net", new Map([[oldTs, oldTs]]));
    assert.strictEqual(dedup._store.get("aaa@s.whatsapp.net").size, 1);

    dedup.prune();
    // After prune, old entry removed
    const jidMap = dedup._store.get("aaa@s.whatsapp.net");
    assert.strictEqual(!jidMap || jidMap.size === 0, true);
  });

  test("multiple JIDs have independent dedup state", () => {
    const { MessageDeduplicator } = require("../lib/dedup");
    const dedup = new MessageDeduplicator(60);
    dedup.isDuplicate("aaa@s.whatsapp.net", 1000);
    dedup.isDuplicate("bbb@s.whatsapp.net", 1000);

    assert.strictEqual(dedup.isDuplicate("aaa@s.whatsapp.net", 1000), true);
    assert.strictEqual(dedup.isDuplicate("bbb@s.whatsapp.net", 1000), true);
    assert.strictEqual(dedup.isDuplicate("ccc@s.whatsapp.net", 1000), false);
  });
});
