/**
 * Tests for lib/allowlist.js
 * Run with: node --test test/allowlist.test.js
 */

const { test, describe, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const os = require("os");

// Helper to write a temp contacts JSON file
function writeTempContacts(contacts, dir) {
  const filePath = path.join(dir, "contactos_agente.json");
  fs.writeFileSync(filePath, JSON.stringify({ contacts }), "utf8");
  return filePath;
}

describe("AllowlistManager", () => {
  let tmpDir;
  let tmpFile;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "allowlist-test-"));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  test("isAllowed returns true for a JID in the contacts list", () => {
    tmpFile = writeTempContacts(
      [{ jid: "5493870123456@s.whatsapp.net" }],
      tmpDir
    );
    const { AllowlistManager } = require("../lib/allowlist");
    const mgr = new AllowlistManager(tmpFile);
    assert.strictEqual(mgr.isAllowed("5493870123456@s.whatsapp.net"), true);
  });

  test("isAllowed returns false for a JID NOT in the contacts list", () => {
    tmpFile = writeTempContacts(
      [{ jid: "5493870123456@s.whatsapp.net" }],
      tmpDir
    );
    const { AllowlistManager } = require("../lib/allowlist");
    const mgr = new AllowlistManager(tmpFile);
    assert.strictEqual(mgr.isAllowed("5499999999999@s.whatsapp.net"), false);
  });

  test("isAllowed returns false when contacts list is empty", () => {
    tmpFile = writeTempContacts([], tmpDir);
    const { AllowlistManager } = require("../lib/allowlist");
    const mgr = new AllowlistManager(tmpFile);
    assert.strictEqual(mgr.isAllowed("5493870123456@s.whatsapp.net"), false);
  });

  test("getJids returns all JIDs from contacts", () => {
    tmpFile = writeTempContacts(
      [
        { jid: "111@s.whatsapp.net" },
        { jid: "222@s.whatsapp.net" },
      ],
      tmpDir
    );
    const { AllowlistManager } = require("../lib/allowlist");
    const mgr = new AllowlistManager(tmpFile);
    assert.deepStrictEqual(mgr.getJids(), [
      "111@s.whatsapp.net",
      "222@s.whatsapp.net",
    ]);
  });

  test("reload updates the in-memory set from file", () => {
    tmpFile = writeTempContacts(
      [{ jid: "5493870123456@s.whatsapp.net" }],
      tmpDir
    );
    const { AllowlistManager } = require("../lib/allowlist");
    const mgr = new AllowlistManager(tmpFile);
    assert.strictEqual(mgr.isAllowed("9999@s.whatsapp.net"), false);

    // Update file and reload
    fs.writeFileSync(
      tmpFile,
      JSON.stringify({ contacts: [{ jid: "9999@s.whatsapp.net" }] }),
      "utf8"
    );
    mgr.reload();
    assert.strictEqual(mgr.isAllowed("9999@s.whatsapp.net"), true);
    assert.strictEqual(mgr.isAllowed("5493870123456@s.whatsapp.net"), false);
  });

  test("missing file logs warning and treats allowlist as empty", () => {
    const { AllowlistManager } = require("../lib/allowlist");
    const mgr = new AllowlistManager("/nonexistent/path/contactos_agente.json");
    assert.strictEqual(mgr.isAllowed("anyone@s.whatsapp.net"), false);
    assert.deepStrictEqual(mgr.getJids(), []);
  });

  test("malformed JSON logs warning and retains previous state", () => {
    tmpFile = writeTempContacts(
      [{ jid: "good@s.whatsapp.net" }],
      tmpDir
    );
    const { AllowlistManager } = require("../lib/allowlist");
    const mgr = new AllowlistManager(tmpFile);
    assert.strictEqual(mgr.isAllowed("good@s.whatsapp.net"), true);

    // Write invalid JSON
    fs.writeFileSync(tmpFile, "NOT_VALID_JSON", "utf8");
    mgr.reload();

    // Previous state retained
    assert.strictEqual(mgr.isAllowed("good@s.whatsapp.net"), true);
  });

  test("contacts without jid field are skipped", () => {
    tmpFile = path.join(tmpDir, "contactos_agente.json");
    fs.writeFileSync(
      tmpFile,
      JSON.stringify({
        contacts: [
          { name: "No JID here" },
          { jid: "valid@s.whatsapp.net" },
        ],
      }),
      "utf8"
    );
    const { AllowlistManager } = require("../lib/allowlist");
    const mgr = new AllowlistManager(tmpFile);
    assert.strictEqual(mgr.isAllowed("valid@s.whatsapp.net"), true);
    assert.strictEqual(mgr.getJids().length, 1);
  });
});
