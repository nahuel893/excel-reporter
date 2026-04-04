/**
 * WhatsApp Service - Microservicio Baileys para envio de reportes.
 *
 * Endpoints:
 *   POST /send-image  — envia imagen a grupo o contacto
 *   POST /send-file   — envia archivo a grupo o contacto
 *   GET  /status      — estado de la sesion WhatsApp
 *
 * Variables de entorno:
 *   PORT         — puerto HTTP (default: 3000)
 *   SESSION_DIR  — directorio para persistir sesion (default: ./session)
 *
 * Primer uso: escanear QR que aparece en consola con WhatsApp Web.
 */

const express = require("express");
const multer = require("multer");
const pino = require("pino");
const fs = require("fs");
const path = require("path");

const logger = pino({ level: "info" });
const app = express();
const upload = multer({ storage: multer.memoryStorage() });

const PORT = parseInt(process.env.PORT || "3000", 10);
const SESSION_DIR = path.resolve(process.env.SESSION_DIR || "./session");

if (!fs.existsSync(SESSION_DIR)) {
  fs.mkdirSync(SESSION_DIR, { recursive: true });
}

// Estado de sesion
let sock = null;
let sessionReady = false;
let phoneNumber = null;

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

  sock.ev.on("connection.update", ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      logger.info("Escanea el QR con WhatsApp para autenticar.");
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
