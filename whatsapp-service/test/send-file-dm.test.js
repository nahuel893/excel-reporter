/**
 * T-107: Tests for POST /send-file-dm endpoint.
 *
 * Strategy: import createSendFileDmRouter from lib/send-file-dm-router.js
 * (extracted from index.js so we can inject a mock sock and test without
 * starting the full Baileys session).
 *
 * Run with: node --test test/send-file-dm.test.js
 *
 * RFs: RF-161, RF-162, RF-163
 */

const { test, describe, beforeEach } = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const path = require("node:path");
const os = require("node:os");
const fs = require("node:fs");
const { Readable } = require("node:stream");

// ---------------------------------------------------------------------------
// Helpers: start an express app on a random port and make requests
// ---------------------------------------------------------------------------

/**
 * Start an express app on an ephemeral port.
 * Returns { server, port, close() }.
 */
function startApp(app) {
  return new Promise((resolve, reject) => {
    const server = app.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolve({ server, port, close: () => new Promise((r) => server.close(r)) });
    });
    server.once("error", reject);
  });
}

/**
 * Make a multipart/form-data POST to a local server.
 *
 * @param {number} port
 * @param {string} urlPath  — e.g. "/send-file-dm"
 * @param {Record<string, string>} fields — plain text fields
 * @param {Buffer|null} fileBuffer — optional file buffer (field name "file")
 * @param {string} [fileName]
 * @returns {Promise<{ status: number, body: object }>}
 */
function multipartPost(port, urlPath, fields, fileBuffer = null, fileName = "test.xlsx") {
  return new Promise((resolve, reject) => {
    const boundary = "----TestBoundary" + Math.random().toString(36).slice(2);

    const parts = [];

    for (const [key, val] of Object.entries(fields)) {
      parts.push(
        `--${boundary}\r\nContent-Disposition: form-data; name="${key}"\r\n\r\n${val}\r\n`
      );
    }

    if (fileBuffer) {
      parts.push(
        `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${fileName}"\r\nContent-Type: application/octet-stream\r\n\r\n`
      );
    }

    const prefix = Buffer.from(parts.join(""));
    const suffix = Buffer.from(`\r\n--${boundary}--\r\n`);

    let body;
    if (fileBuffer) {
      body = Buffer.concat([prefix, fileBuffer, suffix]);
    } else {
      body = Buffer.concat([prefix, suffix]);
    }

    const options = {
      hostname: "127.0.0.1",
      port,
      path: urlPath,
      method: "POST",
      headers: {
        "Content-Type": `multipart/form-data; boundary=${boundary}`,
        "Content-Length": body.length,
      },
    };

    const req = http.request(options, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => {
        let parsed;
        try {
          parsed = JSON.parse(Buffer.concat(chunks).toString());
        } catch {
          parsed = {};
        }
        resolve({ status: res.statusCode, body: parsed });
      });
    });

    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

// ---------------------------------------------------------------------------
// Build test app using the extracted router factory
// ---------------------------------------------------------------------------

function buildTestApp(sockOverride, sessionReady = true) {
  const express = require("express");
  const { createSendFileDmRouter } = require("../lib/send-file-dm-router");

  const app = express();
  app.use(express.json());

  const getSessionReady = () => sessionReady;
  app.use("/send-file-dm", createSendFileDmRouter(sockOverride, getSessionReady));

  return app;
}

// ---------------------------------------------------------------------------
// T-107 tests
// ---------------------------------------------------------------------------

describe("POST /send-file-dm", () => {
  const VALID_JID = "5493870000000@s.whatsapp.net";
  const FAKE_FILE = Buffer.from("PK\x03\x04" + "\x00".repeat(20));

  test("200 with valid JID and file — sock.sendMessage called", async () => {
    const calls = [];
    const mockSock = {
      sendMessage: async (to, msg) => {
        calls.push({ to, msg });
      },
    };

    const app = buildTestApp(mockSock, true);
    const { port, close } = await startApp(app);

    try {
      const { status, body } = await multipartPost(
        port,
        "/send-file-dm",
        { to: VALID_JID, caption: "reporte mensual" },
        FAKE_FILE,
        "report.xlsx"
      );
      assert.strictEqual(status, 200);
      assert.strictEqual(body.ok, true);
      assert.strictEqual(calls.length, 1);
      assert.strictEqual(calls[0].to, VALID_JID);
    } finally {
      await close();
    }
  });

  test("400 when to does not end with @s.whatsapp.net", async () => {
    const mockSock = { sendMessage: async () => {} };
    const app = buildTestApp(mockSock, true);
    const { port, close } = await startApp(app);

    try {
      const { status, body } = await multipartPost(
        port,
        "/send-file-dm",
        { to: "invalid-format" },
        FAKE_FILE
      );
      assert.strictEqual(status, 400);
      assert.strictEqual(body.ok, false);
    } finally {
      await close();
    }
  });

  test("400 when to is a group JID (@g.us)", async () => {
    const mockSock = { sendMessage: async () => {} };
    const app = buildTestApp(mockSock, true);
    const { port, close } = await startApp(app);

    try {
      const { status, body } = await multipartPost(
        port,
        "/send-file-dm",
        { to: "123456789@g.us" },
        FAKE_FILE
      );
      assert.strictEqual(status, 400);
      assert.strictEqual(body.ok, false);
    } finally {
      await close();
    }
  });

  test("400 when no file is provided", async () => {
    const mockSock = { sendMessage: async () => {} };
    const app = buildTestApp(mockSock, true);
    const { port, close } = await startApp(app);

    try {
      const { status, body } = await multipartPost(
        port,
        "/send-file-dm",
        { to: VALID_JID }
        // no file
      );
      assert.strictEqual(status, 400);
      assert.strictEqual(body.ok, false);
    } finally {
      await close();
    }
  });

  test("503 when session is not ready", async () => {
    const mockSock = { sendMessage: async () => {} };
    const app = buildTestApp(mockSock, false); // sessionReady=false
    const { port, close } = await startApp(app);

    try {
      const { status, body } = await multipartPost(
        port,
        "/send-file-dm",
        { to: VALID_JID },
        FAKE_FILE
      );
      assert.strictEqual(status, 503);
      assert.strictEqual(body.ok, false);
    } finally {
      await close();
    }
  });

  test("200 with no caption — sends without caption field", async () => {
    const calls = [];
    const mockSock = {
      sendMessage: async (to, msg) => {
        calls.push({ to, msg });
      },
    };

    const app = buildTestApp(mockSock, true);
    const { port, close } = await startApp(app);

    try {
      const { status, body } = await multipartPost(
        port,
        "/send-file-dm",
        { to: VALID_JID },   // no caption
        FAKE_FILE,
        "data.csv"
      );
      assert.strictEqual(status, 200);
      assert.strictEqual(body.ok, true);
      assert.strictEqual(calls.length, 1);
      // caption should be undefined or not passed as a string when absent
      assert.ok(calls[0].msg.document instanceof Buffer);
    } finally {
      await close();
    }
  });
});
