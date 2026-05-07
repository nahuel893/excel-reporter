/**
 * lib/send-file-dm-router.js — Express router factory for POST /send-file-dm.
 *
 * T-106: Delivers a file as a WhatsApp DM document to a specific JID.
 *
 * Design (RF-161, RF-162, RF-163):
 *   - Accepts multipart/form-data with fields: to (string), caption (string optional), file (binary).
 *   - Validates that `to` ends with @s.whatsapp.net (DM only); returns 400 otherwise.
 *   - Validates that a file was uploaded; returns 400 if missing.
 *   - Calls sock.sendMessage(to, { document, mimetype, fileName, caption }) using in-memory buffer.
 *   - Returns { ok: true } on success, { ok: false, error: string } on failure.
 *   - The existing /send-file endpoint is NOT modified (RF-163).
 *
 * Uses multer memoryStorage (consistent with index.js upload instance).
 * Exported as a factory so the router can be tested with an injected sock mock.
 */

"use strict";

const express = require("express");
const multer = require("multer");
const pino = require("pino");

const logger = pino({ level: "info" });

// Use in-memory storage — no temp files to clean up on this route.
const upload = multer({ storage: multer.memoryStorage() });

/**
 * Create an Express Router for POST /send-file-dm.
 *
 * @param {object} sock — Baileys socket (or mock) with sendMessage().
 * @param {() => boolean} getSessionReady — returns current session readiness.
 * @returns {express.Router}
 */
function createSendFileDmRouter(sock, getSessionReady) {
  const router = express.Router();

  router.post("/", upload.single("file"), async (req, res) => {
    if (!getSessionReady()) {
      return res.status(503).json({ ok: false, error: "session not ready" });
    }

    const { to, caption } = req.body || {};

    // RF-162: to must end with @s.whatsapp.net (DM only)
    if (!to || typeof to !== "string" || !to.endsWith("@s.whatsapp.net")) {
      return res.status(400).json({
        ok: false,
        error: "invalid 'to' jid: must end with @s.whatsapp.net (DMs only)",
      });
    }

    if (!req.file) {
      return res.status(400).json({ ok: false, error: "no file uploaded" });
    }

    try {
      const buffer = req.file.buffer;
      const mimetype = req.file.mimetype || "application/octet-stream";
      const fileName = req.file.originalname || "file";

      const messageContent = {
        document: buffer,
        mimetype,
        fileName,
      };
      if (caption && typeof caption === "string") {
        messageContent.caption = caption;
      }

      await sock.sendMessage(to, messageContent);

      logger.info(
        { to: to.slice(0, 12) + "...", fileName, size: buffer.length },
        "File sent via /send-file-dm"
      );
      res.json({ ok: true });
    } catch (err) {
      logger.error({ err: err.message }, "Error in /send-file-dm");
      res.status(500).json({ ok: false, error: String(err) });
    }
  });

  return router;
}

module.exports = { createSendFileDmRouter };
