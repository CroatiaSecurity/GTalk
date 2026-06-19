# 💬 GTalk

> **Global P2P Messenger** — Finds users worldwide via BitTorrent DHT. No servers, no accounts. Open and chat.

Available as both a **Python desktop app** and a **Flutter app** (Android, iOS, Windows, macOS, Linux).

---

## How It Works

1. Open GTalk on any device
2. App joins the global BitTorrent DHT network
3. Discovers other GTalk users automatically (same as torrent magnet links)
4. Users appear in your contact list — tap to DM or chat in Global Room
5. Share links, music, videos — URLs are clickable

**No servers. No sign-up. No IP addresses. Just open and talk.**

---

## Platforms

| Platform | Technology | Status |
|----------|-----------|--------|
| Android | Flutter | ✅ |
| iOS | Flutter | ✅ |
| Windows | Flutter + Python | ✅ |
| macOS | Flutter + Python | ✅ |
| Linux | Flutter + Python (.deb, AppImage) | ✅ |

---

## Install

### Mobile (Flutter)
```bash
cd flutter
flutter pub get
flutter run
```

### Desktop (Python — lightweight alternative)
```bash
pip install PyQt6 libtorrent cryptography
python gtalk.py
```

### Build standalone
```bash
# Flutter (all platforms)
cd flutter && flutter build apk     # Android
cd flutter && flutter build ios     # iOS
cd flutter && flutter build windows # Windows
cd flutter && flutter build linux   # Linux

# Python (desktop only)
pip install pyinstaller
pyinstaller --onefile --windowed --name GTalk gtalk.py
```

---

## Features

- 🌐 Global DHT peer discovery (BitTorrent protocol)
- 💬 1:1 DMs + Global chat room
- 🔗 Clickable links (Spotify, YouTube, anything)
- 🔒 E2E encryption (X25519 + AES-GCM)
- 📱 Works on phones AND desktops
- 🔔 Notifications when minimized
- 💾 Local chat history
- 🎨 Chrome-dark theme

---

## License & Disclaimer

This project is provided "AS IS", without warranties of any kind.

---

<p align="center">
  <sub>Built with care by <strong>Gorstak</strong></sub>
</p>
