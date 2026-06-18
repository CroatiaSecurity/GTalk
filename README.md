# 💬 GTalk

> **Encrypted P2P Chat** — Cross-platform desktop app with end-to-end encryption, LAN auto-discovery, and Chrome-dark theme.

Built with Python 3.10+ and PyQt6. Runs on Windows, macOS, and Linux.

---

## Features

- 🔒 **End-to-end encryption** — X25519 key exchange + AES-256-GCM per session
- 📡 **LAN auto-discovery** — peers on the same network find each other via UDP broadcast
- 🔄 **Auto-reconnect** — dropped connections re-establish automatically
- 💬 **Real-time messaging** — framed binary protocol with typing indicators
- 🖥️ **System tray** — minimize to tray, desktop notifications on new messages
- 📎 **File sharing** (protocol ready, UI placeholder)
- 💾 **Chat history** — persisted locally (last 2000 messages)
- 🎨 **Chrome-dark theme** — matching GBrowser/Ceprkac
- 🌐 **Cross-platform** — Windows, macOS, Linux
- 🚫 **No accounts, no cloud, no tracking** — everything is direct P2P

---

## Quick Start

```bash
pip install PyQt6 cryptography
python gtalk.py
```

### Connect to someone
1. Both users run GTalk
2. **Same LAN?** → peers appear automatically in "LAN Peers" (double-click to connect)
3. **Different network?** → share your IP, type it in "Connect" field

### Build standalone
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name GTalk gtalk.py
```

---

## Security

- **Key exchange**: X25519 (Curve25519 ECDH)
- **Encryption**: AES-256-GCM with random 96-bit nonce per message
- **No stored keys**: Fresh keypair generated each session
- **Fallback**: If `cryptography` package is missing, runs unencrypted (shows ⚠️ in UI)
- Lock icon (🔒) shown next to peers with active encryption

---

## Protocol

Binary framed: `[4-byte big-endian length][encrypted JSON payload]`

Message types:
- `hello` — handshake with username + X25519 public key
- `message` — chat message with sender, text, timestamp, unique ID
- `typing` — typing indicator
- `file_offer` — file transfer request (filename + size)
- `read_receipt` — message seen acknowledgment

---

## Configuration

Settings stored in `~/.gtalk/settings.json`:
- `username` — display name
- `port` — listening port (default: 12345)
- `notifications` — desktop notifications on/off
- `auto_reconnect` — reconnect to known peers on disconnect

---

## Requirements

- Python 3.10+
- PyQt6 (GUI)
- cryptography (E2E encryption — optional but strongly recommended)

---

## License & Disclaimer

This project is provided "AS IS", without warranties of any kind.

---

<p align="center">
  <sub>Built with care by <strong>Gorstak</strong></sub>
</p>
