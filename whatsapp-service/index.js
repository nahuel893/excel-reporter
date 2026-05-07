/**
 * WhatsApp Service - Microservicio Baileys para envio de reportes y agente BD.
 *
 * Endpoints (send):
 *   POST /send-image  — envia imagen a grupo o contacto
 *   POST /send-file   — envia archivo a grupo o contacto
 *   POST /send-text   — envia texto a un JID DM (para respuestas del agente BD)
 *   GET  /status      — estado de la sesion WhatsApp
 *
 * Inbound (agente BD):
 *   Mensajes DM entrantes de contactos en allowlist se reenvian via POST al
 *   endpoint Python definido en PYTHON_AGENT_URL.
 *
 * Variables de entorno:
 *   PORT              — puerto HTTP (default: 3000)
 *   SESSION_DIR       — directorio para persistir sesion (default: ./session)
 *   PYTHON_AGENT_URL  — URL del webhook Python del agente (default: http://localhost:8000/agent/message)
 *
 * Primer uso: escanear QR que aparece en consola con WhatsApp Web.
 */

const express = require("express");
const multer = require("multer");
const pino = require("pino");
const fs = require("fs");
const path = require("path");
const http = require("http");
const https = require("https");

const { AllowlistManager } = require("./lib/allowlist");
const { MessageDeduplicator } = require("./lib/dedup");

const logger = pino({ level: "info" });
const app = express();
const upload = multer({ storage: multer.memoryStorage() });

const PORT = parseInt(process.env.PORT || "3000", 10);
const SESSION_DIR = path.resolve(process.env.SESSION_DIR || "./session");
const PYTHON_AGENT_URL =
  process.env.PYTHON_AGENT_URL || "http://localhost:8000/agent/message";

// Allowlist file: one level up from whatsapp-service/
const ALLOWLIST_PATH = path.join(
  __dirname,
  "..",
  "configs",
  "contactos_agente.json"
);

if (!fs.existsSync(SESSION_DIR)) {
  fs.mkdirSync(SESSION_DIR, { recursive: true });
}

// Estado de sesion
let sock = null;
let sessionReady = false;
let phoneNumber = null;

// Allowlist manager — hot-reloaded every 5 seconds via fs.watchFile
const allowlist = new AllowlistManager(ALLOWLIST_PATH);
fs.watchFile(ALLOWLIST_PATH, { interval: 5000 }, () => {
  logger.info({ file: ALLOWLIST_PATH }, "Allowlist file changed — recargando");
  allowlist.reload();
});

// Message deduplicator — 60s window per JID
const dedup = new MessageDeduplicator(60);

/**
 * Forwards an inbound DM to the Python BD agent webhook.
 * Fire-and-forget: on network error, logs warning and does NOT retry.
 *
 * @param {string} from  — sender JID (e.g. "549387...@s.whatsapp.net")
 * @param {string} text  — message body
 * @param {number} ts    — Unix timestamp in seconds
 */
function forwardToAgent(from, text, ts) {
  const body = JSON.stringify({ from, text, ts });
  const url = new URL(PYTHON_AGENT_URL);
  const isHttps = url.protocol === "https:";
  const transport = isHttps ? https : http;
  const options = {
    hostname: url.hostname,
    port: url.port || (isHttps ? 443 : 80),
    path: url.pathname + url.search,
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Content-Length": Buffer.byteLength(body),
    },
  };

  const req = transport.request(options, (res) => {
    logger.info(
      { from, ts, status: res.statusCode },
      "Mensaje reenviado al agente BD"
    );
  });

  req.on("error", (err) => {
    logger.warn(
      { from, ts, err: err.message, url: PYTHON_AGENT_URL },
      "No se pudo reenviar mensaje al agente BD — Python no disponible"
    );
  });

  req.write(body);
  req.end();
}

/**
 * Inicializa la conexion con WhatsApp via Baileys.
 * Muestra QR en consola para autenticacion inicial.
 */
async function initWhatsApp() {
  const {
    default: makeWASocket,
    useMultiFileAuthState,
    DisconnectReason,
    fetchLatestBaileysVersion,
  } = await import("@whiskeysockets/baileys");

  const { state, saveCreds } = await useMultiFileAuthState(SESSION_DIR);
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    auth: state,
    logger: pino({ level: "silent" }),
    printQRInTerminal: true,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", async ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      logger.info("Escanea el QR con WhatsApp para autenticar.");
      try {
        const { default: qrcodeTerminal } = await import("qrcode-terminal");
        qrcodeTerminal.generate(qr, { small: true });
      } catch {
        // qrcode-terminal not installed, print raw QR string
        console.log("\nQR (escanea con WhatsApp):\n" + qr + "\n");
      }
    }
    if (connection === "close") {
      const shouldReconnect =
        lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut;
      sessionReady = false;
      logger.warn(
        { statusCode: lastDisconnect?.error?.output?.statusCode },
        "Conexion cerrada. Reconectando: %s",
        shouldReconnect
      );
      if (shouldReconnect) {
        setTimeout(initWhatsApp, 5000);
      }
    }
    if (connection === "open") {
      sessionReady = true;
      phoneNumber = sock.user?.id?.split(":")[0] || null;
      logger.info({ phone: phoneNumber }, "WhatsApp conectado");
    }
  });

  // T-080: Inbound handler — forward DMs from allowlisted contacts to Python agent
  sock.ev.on("messages.upsert", ({ messages, type }) => {
    // Only process new messages (not history syncs)
    if (type !== "notify") return;

    for (const msg of messages) {
      // Skip own messages
      if (msg.key?.fromMe) continue;

      // DMs only: JID must end with @s.whatsapp.net (not @g.us for groups)
      const from = msg.key?.remoteJid || "";
      if (!from.endsWith("@s.whatsapp.net")) continue;

      // Extract text from various message types
      const text =
        msg.message?.conversation ||
        msg.message?.extendedTextMessage?.text ||
        null;
      if (!text) continue;

      // Unix timestamp in seconds
      const ts = Number(msg.messageTimestamp) || Math.floor(Date.now() / 1000);

      // Allowlist check
      if (!allowlist.isAllowed(from)) {
        logger.debug({ from }, "Mensaje ignorado — JID no en allowlist");
        continue;
      }

      // Dedup check
      if (dedup.isDuplicate(from, ts)) {
        logger.debug({ from, ts }, "Mensaje duplicado ignorado");
        continue;
      }

      logger.info({ from, ts, textLen: text.length }, "Mensaje entrante aceptado — reenviando al agente BD");
      forwardToAgent(from, text, ts);
    }
  });
}

/**
 * Resuelve el JID de WhatsApp para un nombre de grupo o contacto.
 * Para grupos: busca en la lista de grupos del usuario.
 * Para contactos: espera que sea un numero en formato internacional.
 */
async function resolveJid(groupName) {
  if (!sock) throw new Error("Socket no inicializado");

  // Intentar buscar como grupo
  try {
    const groups = await sock.groupFetchAllParticipating();
    const match = Object.values(groups).find(
      (g) => g.subject.toLowerCase() === groupName.toLowerCase()
    );
    if (match) return match.id;
  } catch {
    // Si falla la busqueda de grupos, seguir con contacto individual
  }

  // Asumir que es numero de contacto individual (sin @s.whatsapp.net)
  const cleaned = groupName.replace(/[^0-9]/g, "");
  return `${cleaned}@s.whatsapp.net`;
}

// Middleware: verificar sesion lista
function requireSession(req, res, next) {
  if (!sessionReady) {
    return res.status(503).json({
      error: "session_not_ready",
      message: "WhatsApp no autenticado. Escanea el QR en consola.",
    });
  }
  next();
}

// GET /status
app.get("/status", (req, res) => {
  res.json({ connected: sessionReady, phone: phoneNumber });
});

// POST /send-text (T-081)
// Used by Python BD agent to send reply text to a DM contact.
// Body: { to: string, text: string }
// Returns: { ok: true } | { ok: false, error: string }
app.use(express.json());
app.post("/send-text", requireSession, async (req, res) => {
  const { to, text } = req.body || {};

  if (!to || typeof to !== "string") {
    return res.status(400).json({ ok: false, error: "to es requerido (string)" });
  }
  if (!text || typeof text !== "string") {
    return res.status(400).json({ ok: false, error: "text es requerido (string)" });
  }
  // DMs only
  if (!to.endsWith("@s.whatsapp.net")) {
    return res.status(400).json({
      ok: false,
      error: "to debe terminar en @s.whatsapp.net (solo DMs)",
    });
  }

  try {
    await sock.sendMessage(to, { text });
    logger.info({ to, textLen: text.length }, "Texto enviado via /send-text");
    res.json({ ok: true });
  } catch (err) {
    logger.error({ err, to }, "Error enviando texto via /send-text");
    res.status(500).json({ ok: false, error: err.message });
  }
});

// POST /send-image
app.post(
  "/send-image",
  requireSession,
  upload.single("image"),
  async (req, res) => {
    const { group_name, caption = "" } = req.body;
    if (!group_name) {
      return res.status(400).json({ error: "group_name es requerido" });
    }
    if (!req.file) {
      return res.status(400).json({ error: "image es requerido" });
    }
    try {
      const jid = await resolveJid(group_name);
      await sock.sendMessage(jid, {
        image: req.file.buffer,
        caption,
        mimetype: req.file.mimetype || "image/png",
      });
      logger.info({ jid, group_name }, "Imagen enviada");
      res.json({ success: true, message: `Imagen enviada a ${group_name}` });
    } catch (err) {
      logger.error({ err }, "Error enviando imagen");
      res.status(500).json({ success: false, message: err.message });
    }
  }
);

// POST /send-file
app.post(
  "/send-file",
  requireSession,
  upload.single("file"),
  async (req, res) => {
    const { group_name, caption = "" } = req.body;
    if (!group_name) {
      return res.status(400).json({ error: "group_name es requerido" });
    }
    if (!req.file) {
      return res.status(400).json({ error: "file es requerido" });
    }
    try {
      const jid = await resolveJid(group_name);
      await sock.sendMessage(jid, {
        document: req.file.buffer,
        fileName: req.file.originalname,
        caption,
        mimetype:
          req.file.mimetype ||
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      });
      logger.info({ jid, group_name }, "Archivo enviado");
      res.json({ success: true, message: `Archivo enviado a ${group_name}` });
    } catch (err) {
      logger.error({ err }, "Error enviando archivo");
      res.status(500).json({ success: false, message: err.message });
    }
  }
);

// Iniciar servidor
app.listen(PORT, () => {
  logger.info({ port: PORT }, "WhatsApp service iniciado");
  initWhatsApp().catch((err) => {
    logger.error({ err }, "Error inicializando WhatsApp");
  });
});
