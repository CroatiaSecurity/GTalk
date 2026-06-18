# GTalk — Global P2P Chat via DHT Discovery
# Open the app → auto-discovers all GTalk users worldwide via BitTorrent DHT
# No servers, no IPs, no configuration. Just open and chat.
#
# Python 3.10+ / PyQt6 / libtorrent (DHT) / Chrome-dark theme
import sys
import os
import json
import socket
import struct
import threading
import time
import hashlib
import secrets
from datetime import datetime
from pathlib import Path
from PyQt6.QtWidgets import *
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QIcon, QPixmap, QAction

# DHT via libtorrent (pip install libtorrent or python-libtorrent)
try:
    import libtorrent as lt
    HAS_LT = True
except ImportError:
    HAS_LT = False

# Encryption
try:
    from cryptography.hazmat.primitives.asymmetric.x25519 import (
        X25519PrivateKey, X25519PublicKey)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import serialization
    import base64
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

APP_VERSION = "2.1.0"
APP_NAME = "GTalk"
CHAT_PORT = 31337
# GTalk swarm identifier (SHA1 hash used as info_hash in DHT)
GTALK_SWARM_HASH = hashlib.sha1(b"GTalk-Global-Chat-v2").digest()

# === CONFIG ===
CONFIG_DIR = Path.home() / ".gtalk"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = CONFIG_DIR / "history.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"

class Theme:
    Background  = "#202124"
    Surface     = "#292A2D"
    SurfaceAlt  = "#35363A"
    Sidebar     = "#1C1C1F"
    Input       = "#3C4043"
    Border      = "#3C4043"
    Text        = "#FFFFFF"
    TextDim     = "#80868E"
    TextMuted   = "#5F6368"
    Accent      = "#8AB4F8"
    Green       = "#81C995"
    Red         = "#F28B82"
    BubbleSelf  = "#1A3A5C"
    BubblePeer  = "#35363A"

def load_settings():
    if SETTINGS_FILE.exists():
        try: return json.loads(SETTINGS_FILE.read_text())
        except: pass
    return {"username": socket.gethostname()}

def save_settings(s):
    SETTINGS_FILE.write_text(json.dumps(s, indent=2))

def load_history():
    if HISTORY_FILE.exists():
        try: return json.loads(HISTORY_FILE.read_text())
        except: pass
    return []

def save_history(msgs):
    HISTORY_FILE.write_text(json.dumps(msgs[-2000:], indent=2))

# === DHT PEER DISCOVERY ===
class DhtDiscovery:
    """Uses BitTorrent DHT to discover GTalk peers globally. No server needed."""

    def __init__(self, port, on_peer_found):
        self._port = port
        self._callback = on_peer_found
        self._session = None
        self._running = False
        self._known_peers = set()

    def start(self):
        if not HAS_LT:
            return
        self._running = True

        settings = lt.settings_pack()
        settings.set_int(lt.settings_pack.alert_mask, lt.alert.category_t.dht_notification)
        settings.set_str(lt.settings_pack.listen_interfaces, f"0.0.0.0:{self._port + 1000}")
        settings.set_bool(lt.settings_pack.enable_dht, True)

        self._session = lt.session(settings)

        # Bootstrap into the global DHT network
        self._session.add_dht_router("router.bittorrent.com", 6881)
        self._session.add_dht_router("dht.transmissionbt.com", 6881)
        self._session.add_dht_router("router.utorrent.com", 6881)
        self._session.add_dht_router("dht.libtorrent.org", 25401)

        threading.Thread(target=self._announce_loop, daemon=True).start()
        threading.Thread(target=self._search_loop, daemon=True).start()

    def _announce_loop(self):
        """Announce our presence on the GTalk swarm periodically."""
        time.sleep(5)  # Wait for DHT bootstrap
        while self._running and self._session:
            try:
                # Announce ourselves on the GTalk info_hash
                self._session.dht_announce(
                    lt.sha1_hash(GTALK_SWARM_HASH),
                    self._port, lt.announce_flags_t.seed)
            except:
                pass
            time.sleep(30)  # Re-announce every 30s

    def _search_loop(self):
        """Search for other GTalk peers on the swarm."""
        time.sleep(8)  # Wait for DHT bootstrap
        while self._running and self._session:
            try:
                # Get peers for our info_hash
                self._session.dht_get_peers(lt.sha1_hash(GTALK_SWARM_HASH))
                time.sleep(2)

                # Process alerts for peer results
                alerts = self._session.pop_alerts()
                for alert in alerts:
                    if isinstance(alert, lt.dht_get_peers_reply_alert):
                        for peer in alert.peers():
                            ip, port = peer
                            if (ip, port) not in self._known_peers:
                                self._known_peers.add((ip, port))
                                self._callback(ip, port)
            except:
                pass
            time.sleep(10)

    def stop(self):
        self._running = False
        if self._session:
            self._session.pause()

    @property
    def peer_count(self):
        return len(self._known_peers)

    @property
    def dht_nodes(self):
        if self._session:
            return self._session.status().dht_nodes
        return 0

# === NETWORK PROTOCOL ===
def send_frame(sock, data: dict):
    raw = json.dumps(data).encode('utf-8')
    sock.sendall(struct.pack('!I', len(raw)) + raw)

def recv_frame(sock) -> dict:
    header = _recv_exact(sock, 4)
    if not header: return None
    length = struct.unpack('!I', header)[0]
    if length > 1024 * 1024: return None  # 1MB max
    raw = _recv_exact(sock, length)
    if not raw: return None
    return json.loads(raw.decode('utf-8'))

def _recv_exact(sock, n):
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk: return None
        data.extend(chunk)
    return bytes(data)


# === SWARM ENGINE ===
class SwarmEngine(QObject):
    """Manages all peer connections. Auto-connects to DHT-discovered peers."""
    message_received = pyqtSignal(str, str, str)  # sender, text, timestamp
    peer_count_changed = pyqtSignal(int)
    status_changed = pyqtSignal(str)
    dht_status = pyqtSignal(int, int)  # dht_nodes, known_peers

    def __init__(self):
        super().__init__()
        self._running = False
        self._peers = {}  # addr -> socket
        self._lock = threading.Lock()
        self._username = "User"
        self._port = CHAT_PORT
        self._dht = None
        self._my_ips = set()

    def configure(self, username):
        self._username = username

    def start(self):
        self._running = True
        self._my_ips = self._get_local_ips()
        # Start TCP listener
        threading.Thread(target=self._listen_loop, daemon=True).start()
        # Start DHT discovery
        self._dht = DhtDiscovery(self._port, self._on_dht_peer_found)
        self._dht.start()
        self.status_changed.emit("Joining DHT network...")
        # Status updater
        threading.Thread(target=self._status_loop, daemon=True).start()

    def _listen_loop(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind(('0.0.0.0', self._port))
            server.listen(50)
            server.settimeout(1.0)
            while self._running:
                try:
                    sock, addr = server.accept()
                    addr_str = f"{addr[0]}:{addr[1]}"
                    threading.Thread(target=self._handle_peer,
                                   args=(sock, addr_str, False), daemon=True).start()
                except socket.timeout: continue
                except: break
        except Exception as e:
            self.status_changed.emit(f"Listen error: {e}")
        finally:
            server.close()

    def _on_dht_peer_found(self, ip, port):
        """Called by DHT when a new GTalk peer is discovered."""
        if ip in self._my_ips: return
        addr = f"{ip}:{port}"
        with self._lock:
            if addr in self._peers: return
        # Try connecting
        threading.Thread(target=self._connect_to, args=(ip, port), daemon=True).start()

    def _connect_to(self, ip, port):
        addr = f"{ip}:{port}"
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((ip, port))
            sock.settimeout(None)
            self._handle_peer(sock, addr, True)
        except:
            pass

    def _handle_peer(self, sock, addr, is_outgoing):
        # Handshake
        try:
            send_frame(sock, {"type": "hello", "username": self._username, "version": APP_VERSION})
            msg = recv_frame(sock)
            if not msg or msg.get("type") != "hello":
                sock.close()
                return
            peer_name = msg.get("username", addr)
        except:
            sock.close()
            return

        with self._lock:
            if addr in self._peers:
                sock.close()
                return
            self._peers[addr] = sock

        self.peer_count_changed.emit(len(self._peers))

        # Receive loop
        while self._running:
            try:
                msg = recv_frame(sock)
                if msg is None: break
                if msg.get("type") == "message":
                    self.message_received.emit(
                        msg.get("sender", peer_name),
                        msg.get("text", ""),
                        msg.get("timestamp", ""))
            except: break

        with self._lock:
            self._peers.pop(addr, None)
        try: sock.close()
        except: pass
        self.peer_count_changed.emit(len(self._peers))

    def send_message(self, text):
        msg = {
            "type": "message",
            "sender": self._username,
            "text": text,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        }
        with self._lock:
            dead = []
            for addr, sock in self._peers.items():
                try: send_frame(sock, msg)
                except: dead.append(addr)
            for a in dead:
                self._peers.pop(a, None)
                try: pass
                except: pass
        if dead:
            self.peer_count_changed.emit(len(self._peers))

    def _status_loop(self):
        while self._running:
            time.sleep(5)
            if self._dht:
                self.dht_status.emit(self._dht.dht_nodes, self._dht.peer_count)

    def _get_local_ips(self):
        ips = {'127.0.0.1'}
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ips.add(info[4][0])
        except: pass
        return ips

    def stop(self):
        self._running = False
        if self._dht: self._dht.stop()
        with self._lock:
            for sock in self._peers.values():
                try: sock.close()
                except: pass
            self._peers.clear()

# === CHAT BUBBLE ===
class ChatBubble(QFrame):
    def __init__(self, sender, text, timestamp, is_self=False, is_system=False):
        super().__init__()
        self.setObjectName("bubble")
        if is_system:
            self.setStyleSheet(f"#bubble {{ background: {Theme.Surface}; border-radius: 8px; padding: 4px 12px; margin: 4px 60px; }}")
            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color: {Theme.TextMuted}; font-size: 11px; font-style: italic;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)
            return

        bg = Theme.BubbleSelf if is_self else Theme.BubblePeer
        margin = "2px 50px 2px 12px" if not is_self else "2px 12px 2px 50px"
        self.setStyleSheet(f"#bubble {{ background: {bg}; border-radius: 12px; padding: 8px 12px; margin: {margin}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        header = QHBoxLayout()
        s_lbl = QLabel(sender)
        s_lbl.setStyleSheet(f"color: {Theme.Accent if not is_self else Theme.Green}; font-size: 11px; font-weight: bold;")
        t_lbl = QLabel(timestamp)
        t_lbl.setStyleSheet(f"color: {Theme.TextMuted}; font-size: 10px;")
        t_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        header.addWidget(s_lbl)
        header.addStretch()
        header.addWidget(t_lbl)
        layout.addLayout(header)

        m_lbl = QLabel(text)
        m_lbl.setWordWrap(True)
        m_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        m_lbl.setStyleSheet(f"color: {Theme.Text}; font-size: 13px;")
        layout.addWidget(m_lbl)

# === MAIN WINDOW ===
class GTalkWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.messages = load_history()

        self.setWindowTitle("GTalk")
        self.setMinimumSize(600, 450)
        self.resize(750, 550)

        # Window icon (same as tray)
        pix = QPixmap(64, 64)
        pix.fill(QColor(Theme.Accent))
        self.setWindowIcon(QIcon(pix))

        # Swarm
        self.swarm = SwarmEngine()
        self.swarm.configure(self.settings['username'])
        self.swarm.message_received.connect(self._on_message)
        self.swarm.peer_count_changed.connect(self._on_peers_changed)
        self.swarm.status_changed.connect(self._on_status)
        self.swarm.dht_status.connect(self._on_dht_status)
        self.swarm.start()

        self._build_ui()
        self._build_tray()
        self._apply_theme()
        self._load_history()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # TOP BAR (status + username)
        top = QFrame()
        top.setObjectName("topBar")
        top_l = QHBoxLayout(top)
        top_l.setContentsMargins(16, 8, 16, 8)

        logo = QLabel("💬 GTalk")
        logo.setStyleSheet(f"color: {Theme.Accent}; font-size: 15px; font-weight: bold;")
        top_l.addWidget(logo)

        self.dht_lbl = QLabel("Joining DHT...")
        self.dht_lbl.setStyleSheet(f"color: {Theme.TextMuted}; font-size: 11px;")
        top_l.addWidget(self.dht_lbl)
        top_l.addStretch()

        self.peers_lbl = QLabel("0 peers")
        self.peers_lbl.setStyleSheet(f"color: {Theme.Green}; font-size: 11px; font-weight: bold;")
        top_l.addWidget(self.peers_lbl)

        top_l.addSpacing(16)
        top_l.addWidget(QLabel("Name:"))
        self.name_input = QLineEdit(self.settings['username'])
        self.name_input.setMaximumWidth(120)
        self.name_input.editingFinished.connect(self._save_name)
        top_l.addWidget(self.name_input)

        layout.addWidget(top)

        # CHAT AREA
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setObjectName("chatScroll")
        self.chat_widget = QWidget()
        self.chat_vbox = QVBoxLayout(self.chat_widget)
        self.chat_vbox.setContentsMargins(16, 16, 16, 16)
        self.chat_vbox.setSpacing(3)
        self.chat_vbox.addStretch()
        self.scroll.setWidget(self.chat_widget)
        layout.addWidget(self.scroll)

        # INPUT BAR
        input_frame = QFrame()
        input_frame.setObjectName("inputBar")
        il = QHBoxLayout(input_frame)
        il.setContentsMargins(16, 8, 16, 8)

        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("Type a message... (peers are discovered automatically)")
        self.msg_input.setObjectName("msgInput")
        self.msg_input.returnPressed.connect(self._send)
        il.addWidget(self.msg_input)

        send_btn = QPushButton("Send")
        send_btn.setObjectName("accentBtn")
        send_btn.clicked.connect(self._send)
        il.addWidget(send_btn)

        layout.addWidget(input_frame)

    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable(): return
        self.tray = QSystemTrayIcon(self)
        pix = QPixmap(32, 32)
        pix.fill(QColor(Theme.Accent))
        self.tray.setIcon(QIcon(pix))
        menu = QMenu()
        menu.addAction(QAction("Show", self, triggered=self.show))
        menu.addAction(QAction("Quit", self, triggered=self._quit))
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.show() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background: {Theme.Background}; color: {Theme.Text}; font-family: 'Segoe UI Variable', 'Segoe UI', sans-serif; font-size: 13px; }}
            #topBar {{ background: {Theme.Sidebar}; border-bottom: 1px solid {Theme.Border}; }}
            #chatScroll {{ background: {Theme.Background}; border: none; }}
            #inputBar {{ background: {Theme.Surface}; border-top: 1px solid {Theme.Border}; }}
            #msgInput {{ background: {Theme.Input}; color: {Theme.Text}; border: 1px solid {Theme.Border}; border-radius: 18px; padding: 8px 16px; font-size: 13px; }}
            #msgInput:focus {{ border-color: {Theme.Accent}; }}
            #accentBtn {{ background: {Theme.Accent}; color: #202124; border: none; border-radius: 6px; padding: 8px 18px; font-weight: bold; }}
            #accentBtn:hover {{ background: #AECBFA; }}
            QLineEdit {{ background: {Theme.Surface}; color: {Theme.Text}; border: 1px solid {Theme.Border}; border-radius: 4px; padding: 5px 8px; }}
            QLabel {{ color: {Theme.TextDim}; }}
            QPushButton {{ background: {Theme.SurfaceAlt}; color: {Theme.Text}; border: 1px solid {Theme.Border}; border-radius: 6px; padding: 6px 12px; }}
            QScrollBar:vertical {{ background: {Theme.Background}; width: 8px; }}
            QScrollBar::handle:vertical {{ background: {Theme.SurfaceAlt}; border-radius: 4px; min-height: 30px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QMenu {{ background: {Theme.Surface}; color: {Theme.Text}; border: 1px solid {Theme.Border}; }}
        """)

    def _load_history(self):
        for msg in self.messages[-100:]:
            self._add_bubble(msg['sender'], msg['text'], msg['timestamp'],
                           is_self=(msg['sender'] == self.settings['username']))

    def _add_bubble(self, sender, text, timestamp, is_self=False, is_system=False):
        bubble = ChatBubble(sender, text, timestamp, is_self, is_system)
        self.chat_vbox.insertWidget(self.chat_vbox.count() - 1, bubble)
        QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def _send(self):
        text = self.msg_input.text().strip()
        if not text: return
        self.msg_input.clear()
        ts = datetime.now().strftime("%H:%M:%S")
        self._add_bubble(self.settings['username'], text, ts, is_self=True)
        self.messages.append({"sender": self.settings['username'], "text": text, "timestamp": ts})
        save_history(self.messages)
        self.swarm.send_message(text)

    def _save_name(self):
        new = self.name_input.text().strip()
        if new and new != self.settings['username']:
            self.settings['username'] = new
            self.swarm._username = new
            save_settings(self.settings)

    def _on_message(self, sender, text, timestamp):
        self._add_bubble(sender, text, timestamp, is_self=False)
        self.messages.append({"sender": sender, "text": text, "timestamp": timestamp})
        save_history(self.messages)
        if not self.isActiveWindow() and hasattr(self, 'tray'):
            self.tray.showMessage("GTalk", f"{sender}: {text[:80]}", QSystemTrayIcon.MessageIcon.Information, 3000)

    def _on_peers_changed(self, count):
        self.peers_lbl.setText(f"{count} peer{'s' if count != 1 else ''}")
        self.peers_lbl.setStyleSheet(f"color: {Theme.Green if count > 0 else Theme.TextMuted}; font-size: 11px; font-weight: bold;")

    def _on_status(self, s):
        self.dht_lbl.setText(s)

    def _on_dht_status(self, nodes, peers):
        self.dht_lbl.setText(f"DHT: {nodes} nodes • {peers} discovered")
        if not HAS_LT:
            self.dht_lbl.setText("⚠️ libtorrent not installed — DHT disabled")
            self.dht_lbl.setStyleSheet(f"color: {Theme.Red}; font-size: 11px;")

    def _quit(self):
        self.swarm.stop()
        QApplication.quit()

    def closeEvent(self, event):
        if hasattr(self, 'tray') and self.tray.isVisible():
            self.hide()
            event.ignore()
        else:
            self.swarm.stop()
            event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    w = GTalkWindow()
    w.show()
    if not HAS_LT:
        QMessageBox.warning(w, "GTalk", "libtorrent not found.\nInstall it: pip install libtorrent\n\nDHT discovery won't work without it.")
    sys.exit(app.exec())
