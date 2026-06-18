# 💬 GTalk

> **Global P2P Chat via DHT** — Open the app, it finds other GTalk users worldwide automatically. No servers, no IPs, no configuration.

Uses BitTorrent DHT (same tech as torrents/magnets) for peer discovery. Built with Python 3.10+ and PyQt6.

---

## How It Works

1. You open GTalk
2. It joins the global BitTorrent DHT network (millions of nodes)
3. It announces itself on a GTalk-specific "swarm" (like a magnet link)
4. Other GTalk users are discovered automatically
5. You chat — messages go directly between peers (P2P)

**No servers. No accounts. No IP addresses to type. Just open and talk.**

---

## Features

- 🌐 **Global DHT discovery** — finds GTalk users worldwide via BitTorrent DHT
- 💬 **Real-time P2P messaging** — direct connections, no relay server
- 🖥️ **System tray** — minimize to tray, desktop notifications
- 💾 **Chat history** — last 2000 messages saved locally
- 🎨 **Chrome-dark theme** — matching GBrowser/Ceprkac
- 🔒 **E2E encryption ready** (with `cryptography` package)
- 🚫 **Zero configuration** — no sign-up, no accounts, no cloud

---

## Install & Run

```bash
pip install PyQt6 libtorrent cryptography
python gtalk.py
```

### Build standalone exe
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name GTalk gtalk.py
```

---

## Requirements

- Python 3.10+
- **PyQt6** — GUI
- **libtorrent** — DHT peer discovery (the magic that finds peers globally)
- **cryptography** — E2E encryption (optional but recommended)

---

## How DHT Discovery Works

GTalk uses the same DHT network as BitTorrent clients. On startup:
1. Bootstraps into DHT via `router.bittorrent.com`, `dht.transmissionbt.com`, etc.
2. Announces on a fixed info_hash (`SHA1("GTalk-Global-Chat-v2")`)
3. Periodically searches for other peers announcing the same hash
4. Connects directly to discovered peers over TCP

This is the same mechanism that allows torrents to work without trackers (magnet links).

---

## License & Disclaimer

This project is provided "AS IS", without warranties of any kind.

---

<p align="center">
  <sub>Built with care by <strong>Gorstak</strong></sub>
</p>
