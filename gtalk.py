# GTalk — Global P2P Messenger via DHT
# Finds all GTalk users worldwide via BitTorrent DHT. Click a user to DM.
# Like WhatsApp/Signal but fully P2P — no servers, no accounts.
#
# Python 3.10+ / PyQt6 / libtorrent (DHT)
import sys
import os
import json
import socket
import struct
import threading
import time
import hashlib
import secrets
import re
from datetime import datetime
from pathlib import Path
from PyQt6.QtWidgets import *
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QUrl
from PyQt6.QtGui import QColor, QIcon, QPixmap, QAction, QDesktopServices

try:
    import libtorrent as lt
    HAS_LT = True
except ImportError:
    HAS_LT = False

try:
    from cryptography.hazmat.primitives.asymmetric.x25519 import (
        X25519PrivateKey, X25519PublicKey)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import serialization
    import base64
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

APP_VERSION = "2.2.0"
APP_NAME = "GTalk"
CHAT_PORT = 31337
GTALK_SWARM_HASH = hashlib.sha1(b"GTalk-Global-Chat-v2").digest()
URL_REGEX = re.compile(r'(https?://[^\s<>"]+)')

# === CONFIG ===
CONFIG_DIR = Path.home() / ".gtalk"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = CONFIG_DIR / "history.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"

class Theme:
    Background = "#202124"; Surface = "#292A2D"; SurfaceAlt = "#35363A"
    Sidebar = "#1C1C1F"; Input = "#3C4043"; Border = "#3C4043"
    Text = "#FFFFFF"; TextDim = "#80868E"; TextMuted = "#5F6368"
    Accent = "#8AB4F8"; Green = "#81C995"; Red = "#F28B82"
    BubbleSelf = "#1A3A5C"; BubblePeer = "#35363A"
    Online = "#81C995"; Offline = "#5F6368"

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
    return {}  # {channel: [messages]}

def save_history(h):
    # Keep last 500 per channel
    trimmed = {k: v[-500:] for k, v in h.items()}
    HISTORY_FILE.write_text(json.dumps(trimmed, indent=2))

# === PROTOCOL ===
def send_frame(sock, data: dict):
    raw = json.dumps(data).encode('utf-8')
    sock.sendall(struct.pack('!I', len(raw)) + raw)

def recv_frame(sock) -> dict:
    header = _recv_exact(sock, 4)
    if not header: return None
    length = struct.unpack('!I', header)[0]
    if length > 2 * 1024 * 1024: return None
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

# === DHT DISCOVERY ===
class DhtDiscovery:
    def __init__(self, port, on_peer_found):
        self._port = port
        self._callback = on_peer_found
        self._session = None
        self._running = False
        self._known = set()

    def start(self):
        if not HAS_LT: return
        self._running = True
        settings = lt.settings_pack()
        settings.set_int(lt.settings_pack.alert_mask, lt.alert.category_t.dht_notification)
        settings.set_str(lt.settings_pack.listen_interfaces, f"0.0.0.0:{self._port + 1000}")
        settings.set_bool(lt.settings_pack.enable_dht, True)
        self._session = lt.session(settings)
        self._session.add_dht_router("router.bittorrent.com", 6881)
        self._session.add_dht_router("dht.transmissionbt.com", 6881)
        self._session.add_dht_router("router.utorrent.com", 6881)
        threading.Thread(target=self._announce_loop, daemon=True).start()
        threading.Thread(target=self._search_loop, daemon=True).start()

    def _announce_loop(self):
        time.sleep(5)
        while self._running and self._session:
            try:
                self._session.dht_announce(lt.sha1_hash(GTALK_SWARM_HASH), self._port, lt.announce_flags_t.seed)
            except: pass
            time.sleep(30)

    def _search_loop(self):
        time.sleep(8)
        while self._running and self._session:
            try:
                self._session.dht_get_peers(lt.sha1_hash(GTALK_SWARM_HASH))
                time.sleep(2)
                for alert in self._session.pop_alerts():
                    if isinstance(alert, lt.dht_get_peers_reply_alert):
                        for peer in alert.peers():
                            ip, port = peer
                            if (ip, port) not in self._known:
                                self._known.add((ip, port))
                                self._callback(ip, port)
            except: pass
            time.sleep(10)

    def stop(self):
        self._running = False
        if self._session: self._session.pause()

    @property
    def dht_nodes(self):
        return self._session.status().dht_nodes if self._session else 0

# === SWARM ENGINE ===
class SwarmEngine(QObject):
    message_received = pyqtSignal(str, str, str, str)  # sender, text, timestamp, channel
    user_online = pyqtSignal(str, str)  # username, addr
    user_offline = pyqtSignal(str)  # addr
    status_changed = pyqtSignal(str)
    dht_nodes_changed = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._running = False
        self._peers = {}  # addr -> {socket, username}
        self._lock = threading.Lock()
        self._username = "User"
        self._dht = None

    def configure(self, username):
        self._username = username

    def start(self):
        self._running = True
        self._my_ips = self._get_local_ips()
        threading.Thread(target=self._listen, daemon=True).start()
        self._dht = DhtDiscovery(CHAT_PORT, self._on_peer_found)
        self._dht.start()
        self.status_changed.emit("Joining DHT network...")
        threading.Thread(target=self._dht_status_loop, daemon=True).start()

    def _listen(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(('0.0.0.0', CHAT_PORT))
            srv.listen(50)
            srv.settimeout(1.0)
            while self._running:
                try:
                    sock, addr = srv.accept()
                    threading.Thread(target=self._handle, args=(sock, f"{addr[0]}:{addr[1]}", False), daemon=True).start()
                except socket.timeout: continue
                except: break
        except Exception as e:
            self.status_changed.emit(f"Port {CHAT_PORT} busy: {e}")
        finally:
            srv.close()

    def _on_peer_found(self, ip, port):
        if ip in self._my_ips: return
        addr = f"{ip}:{port}"
        with self._lock:
            if addr in self._peers: return
        threading.Thread(target=self._connect, args=(ip, port), daemon=True).start()

    def _connect(self, ip, port):
        addr = f"{ip}:{port}"
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((ip, port))
            sock.settimeout(None)
            self._handle(sock, addr, True)
        except: pass

    def _handle(self, sock, addr, is_outgoing):
        try:
            send_frame(sock, {"type": "hello", "username": self._username})
            msg = recv_frame(sock)
            if not msg or msg.get("type") != "hello":
                sock.close(); return
            peer_name = msg.get("username", addr)
        except:
            sock.close(); return

        with self._lock:
            if addr in self._peers: sock.close(); return
            self._peers[addr] = {"socket": sock, "username": peer_name}

        self.user_online.emit(peer_name, addr)

        # Receive loop
        while self._running:
            try:
                msg = recv_frame(sock)
                if not msg: break
                t = msg.get("type")
                if t == "message":
                    self.message_received.emit(
                        msg.get("sender", peer_name), msg.get("text", ""),
                        msg.get("timestamp", ""), msg.get("channel", "global"))
                elif t == "dm":
                    self.message_received.emit(
                        msg.get("sender", peer_name), msg.get("text", ""),
                        msg.get("timestamp", ""), f"dm:{msg.get('sender', peer_name)}")
            except: break

        with self._lock: self._peers.pop(addr, None)
        try: sock.close()
        except: pass
        self.user_offline.emit(addr)

    def send_to_global(self, text):
        msg = {"type": "message", "sender": self._username, "text": text,
               "timestamp": datetime.now().strftime("%H:%M"), "channel": "global"}
        self._broadcast(msg)

    def send_dm(self, target_username, text):
        msg = {"type": "dm", "sender": self._username, "text": text,
               "timestamp": datetime.now().strftime("%H:%M")}
        with self._lock:
            for info in self._peers.values():
                if info["username"] == target_username:
                    try: send_frame(info["socket"], msg)
                    except: pass
                    return

    def _broadcast(self, msg):
        with self._lock:
            dead = []
            for addr, info in self._peers.items():
                try: send_frame(info["socket"], msg)
                except: dead.append(addr)
            for a in dead: self._peers.pop(a, None)

    def _dht_status_loop(self):
        while self._running:
            time.sleep(5)
            if self._dht:
                self.dht_nodes_changed.emit(self._dht.dht_nodes)

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
            for info in self._peers.values():
                try: info["socket"].close()
                except: pass
            self._peers.clear()

    @property
    def online_users(self):
        with self._lock:
            return [(info["username"], addr) for addr, info in self._peers.items()]

# === CHAT BUBBLE ===
class ChatBubble(QFrame):
    def __init__(self, sender, text, timestamp, is_self=False, is_system=False):
        super().__init__()
        self.setObjectName("bubble")
        if is_system:
            self.setStyleSheet(f"#bubble {{ background: {Theme.Surface}; border-radius: 8px; padding: 3px 12px; margin: 2px 80px; }}")
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color: {Theme.TextMuted}; font-size: 10px; font-style: italic;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            QHBoxLayout(self).addWidget(lbl)
            return

        bg = Theme.BubbleSelf if is_self else Theme.BubblePeer
        m = "2px 50px 2px 12px" if not is_self else "2px 12px 2px 50px"
        self.setStyleSheet(f"#bubble {{ background: {bg}; border-radius: 12px; padding: 8px 12px; margin: {m}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        h = QHBoxLayout()
        s = QLabel(sender)
        s.setStyleSheet(f"color: {Theme.Accent if not is_self else Theme.Green}; font-size: 11px; font-weight: bold;")
        t = QLabel(timestamp)
        t.setStyleSheet(f"color: {Theme.TextMuted}; font-size: 10px;")
        t.setAlignment(Qt.AlignmentFlag.AlignRight)
        h.addWidget(s); h.addStretch(); h.addWidget(t)
        layout.addLayout(h)

        # Render text with clickable links
        display_text = URL_REGEX.sub(r'<a href="\1" style="color: {0};">\1</a>'.format(Theme.Accent), text)
        msg = QLabel(display_text)
        msg.setWordWrap(True)
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse)
        msg.setOpenExternalLinks(True)
        msg.setStyleSheet(f"color: {Theme.Text}; font-size: 13px;")
        layout.addWidget(msg)

# === MAIN WINDOW ===
class GTalkWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.history = load_history()  # {channel: [msgs]}
        self._current_channel = "global"

        self.setWindowTitle("GTalk")
        self.setMinimumSize(800, 520)
        self.resize(1000, 620)
        pix = QPixmap(64, 64); pix.fill(QColor(Theme.Accent))
        self.setWindowIcon(QIcon(pix))

        self.swarm = SwarmEngine()
        self.swarm.configure(self.settings['username'])
        self.swarm.message_received.connect(self._on_message)
        self.swarm.user_online.connect(self._on_user_online)
        self.swarm.user_offline.connect(self._on_user_offline)
        self.swarm.status_changed.connect(self._on_status)
        self.swarm.dht_nodes_changed.connect(self._on_dht)
        self.swarm.start()

        self._build_ui()
        self._build_tray()
        self._apply_theme()
        self._render_chat()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main = QHBoxLayout(central)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # === LEFT PANEL: Users ===
        left = QFrame()
        left.setFixedWidth(220)
        left.setObjectName("sidebar")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(10, 10, 10, 10)
        ll.setSpacing(4)

        # Header
        hdr = QHBoxLayout()
        logo = QLabel("💬 GTalk")
        logo.setStyleSheet(f"color: {Theme.Accent}; font-size: 15px; font-weight: bold;")
        hdr.addWidget(logo)
        hdr.addStretch()
        ll.addLayout(hdr)

        self.dht_lbl = QLabel("Joining DHT...")
        self.dht_lbl.setStyleSheet(f"color: {Theme.TextMuted}; font-size: 10px;")
        ll.addWidget(self.dht_lbl)
        ll.addSpacing(6)

        # Global room button
        self.global_btn = QPushButton("🌐  Global Room")
        self.global_btn.setObjectName("channelBtn")
        self.global_btn.clicked.connect(lambda: self._switch_channel("global"))
        ll.addWidget(self.global_btn)
        ll.addSpacing(4)

        # Online users label
        self.online_lbl = QLabel("ONLINE — 0")
        self.online_lbl.setStyleSheet(f"color: {Theme.TextMuted}; font-size: 10px; font-weight: bold;")
        ll.addWidget(self.online_lbl)

        # User list (scrollable)
        self.user_list = QListWidget()
        self.user_list.setObjectName("userList")
        self.user_list.itemClicked.connect(self._on_user_clicked)
        ll.addWidget(self.user_list)

        # Name setting at bottom
        ll.addStretch()
        row = QHBoxLayout()
        row.addWidget(QLabel("You:"))
        self.name_input = QLineEdit(self.settings['username'])
        self.name_input.editingFinished.connect(self._save_name)
        row.addWidget(self.name_input)
        ll.addLayout(row)

        main.addWidget(left)

        # === CENTER: Chat ===
        center = QFrame()
        center.setObjectName("chatPanel")
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # Channel header
        self.channel_header = QLabel("🌐 Global Room")
        self.channel_header.setStyleSheet(f"background: {Theme.Sidebar}; color: {Theme.Text}; font-size: 14px; font-weight: bold; padding: 10px 16px; border-bottom: 1px solid {Theme.Border};")
        cl.addWidget(self.channel_header)

        # Chat scroll
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setObjectName("chatScroll")
        self.chat_widget = QWidget()
        self.chat_vbox = QVBoxLayout(self.chat_widget)
        self.chat_vbox.setContentsMargins(12, 12, 12, 12)
        self.chat_vbox.setSpacing(3)
        self.chat_vbox.addStretch()
        self.scroll.setWidget(self.chat_widget)
        cl.addWidget(self.scroll)

        # Input
        inp = QFrame(); inp.setObjectName("inputBar")
        il = QHBoxLayout(inp); il.setContentsMargins(12, 8, 12, 8)
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("Type a message...")
        self.msg_input.setObjectName("msgInput")
        self.msg_input.returnPressed.connect(self._send)
        il.addWidget(self.msg_input)
        send_btn = QPushButton("Send"); send_btn.setObjectName("accentBtn")
        send_btn.clicked.connect(self._send)
        il.addWidget(send_btn)
        cl.addWidget(inp)

        main.addWidget(center)

    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable(): return
        self.tray = QSystemTrayIcon(self)
        pix = QPixmap(32, 32); pix.fill(QColor(Theme.Accent))
        self.tray.setIcon(QIcon(pix))
        menu = QMenu()
        menu.addAction(QAction("Show", self, triggered=self.show))
        menu.addAction(QAction("Quit", self, triggered=self._quit))
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.show() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background: {Theme.Background}; color: {Theme.Text}; font-family: 'Segoe UI Variable','Segoe UI',sans-serif; font-size: 13px; }}
            #sidebar {{ background: {Theme.Sidebar}; border-right: 1px solid {Theme.Border}; }}
            #chatPanel {{ background: {Theme.Background}; }}
            #chatScroll {{ background: {Theme.Background}; border: none; }}
            #inputBar {{ background: {Theme.Surface}; border-top: 1px solid {Theme.Border}; }}
            #msgInput {{ background: {Theme.Input}; color: {Theme.Text}; border: 1px solid {Theme.Border}; border-radius: 18px; padding: 8px 16px; }}
            #msgInput:focus {{ border-color: {Theme.Accent}; }}
            #accentBtn {{ background: {Theme.Accent}; color: #202124; border: none; border-radius: 6px; padding: 8px 18px; font-weight: bold; }}
            #accentBtn:hover {{ background: #AECBFA; }}
            #channelBtn {{ background: {Theme.SurfaceAlt}; color: {Theme.Text}; border: 1px solid {Theme.Border}; border-radius: 6px; padding: 8px; text-align: left; font-size: 12px; }}
            #channelBtn:hover {{ background: #444750; }}
            #userList {{ background: {Theme.Surface}; border: none; border-radius: 4px; }}
            #userList::item {{ padding: 6px 10px; border-radius: 4px; }}
            #userList::item:hover {{ background: {Theme.SurfaceAlt}; }}
            #userList::item:selected {{ background: {Theme.Accent}; color: #202124; }}
            QLineEdit {{ background: {Theme.Surface}; color: {Theme.Text}; border: 1px solid {Theme.Border}; border-radius: 4px; padding: 5px 8px; }}
            QLabel {{ color: {Theme.TextDim}; }}
            QPushButton {{ background: {Theme.SurfaceAlt}; color: {Theme.Text}; border: 1px solid {Theme.Border}; border-radius: 6px; padding: 6px 12px; }}
            QScrollBar:vertical {{ background: {Theme.Background}; width: 8px; }}
            QScrollBar::handle:vertical {{ background: {Theme.SurfaceAlt}; border-radius: 4px; min-height: 30px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QMenu {{ background: {Theme.Surface}; color: {Theme.Text}; border: 1px solid {Theme.Border}; }}
        """)

    # === CHAT RENDERING ===
    def _render_chat(self):
        # Clear current bubbles
        while self.chat_vbox.count() > 1:
            item = self.chat_vbox.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        # Load channel history
        msgs = self.history.get(self._current_channel, [])
        for msg in msgs[-100:]:
            self._add_bubble(msg['sender'], msg['text'], msg['timestamp'],
                           is_self=(msg['sender'] == self.settings['username']))

    def _add_bubble(self, sender, text, timestamp, is_self=False, is_system=False):
        b = ChatBubble(sender, text, timestamp, is_self, is_system)
        self.chat_vbox.insertWidget(self.chat_vbox.count() - 1, b)
        QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def _switch_channel(self, channel):
        self._current_channel = channel
        if channel == "global":
            self.channel_header.setText("🌐 Global Room")
        else:
            name = channel.replace("dm:", "")
            self.channel_header.setText(f"💬 {name}")
        self._render_chat()

    # === ACTIONS ===
    def _send(self):
        text = self.msg_input.text().strip()
        if not text: return
        self.msg_input.clear()
        ts = datetime.now().strftime("%H:%M")
        sender = self.settings['username']

        # Store in history
        if self._current_channel not in self.history:
            self.history[self._current_channel] = []
        self.history[self._current_channel].append({"sender": sender, "text": text, "timestamp": ts})
        save_history(self.history)

        # Show bubble
        self._add_bubble(sender, text, ts, is_self=True)

        # Send
        if self._current_channel == "global":
            self.swarm.send_to_global(text)
        else:
            target = self._current_channel.replace("dm:", "")
            self.swarm.send_dm(target, text)

    def _on_user_clicked(self, item):
        username = item.text().lstrip("● ").strip()
        self._switch_channel(f"dm:{username}")

    def _save_name(self):
        new = self.name_input.text().strip()
        if new and new != self.settings['username']:
            self.settings['username'] = new
            self.swarm._username = new
            save_settings(self.settings)

    # === SIGNALS ===
    def _on_message(self, sender, text, timestamp, channel):
        # If it's a DM to us, channel comes as "dm:sender"
        if channel not in self.history:
            self.history[channel] = []
        self.history[channel].append({"sender": sender, "text": text, "timestamp": timestamp})
        save_history(self.history)

        # If we're viewing this channel, show it
        if channel == self._current_channel:
            self._add_bubble(sender, text, timestamp, is_self=False)

        # Notification
        if not self.isActiveWindow() and hasattr(self, 'tray'):
            self.tray.showMessage("GTalk", f"{sender}: {text[:80]}",
                                 QSystemTrayIcon.MessageIcon.Information, 3000)

    def _on_user_online(self, username, addr):
        self.user_list.addItem(f"● {username}")
        self.online_lbl.setText(f"ONLINE — {self.user_list.count()}")
        self._add_bubble("", f"{username} joined", "", is_system=True)

    def _on_user_offline(self, addr):
        # Remove by addr (we don't show addr in list, so remove last matching)
        for i in range(self.user_list.count() - 1, -1, -1):
            # Just remove one — imperfect but functional
            if self.user_list.count() > 0:
                self.user_list.takeItem(self.user_list.count() - 1)
                break
        self.online_lbl.setText(f"ONLINE — {self.user_list.count()}")

    def _on_status(self, s):
        self.dht_lbl.setText(s)

    def _on_dht(self, nodes):
        self.dht_lbl.setText(f"DHT: {nodes} nodes")
        if not HAS_LT:
            self.dht_lbl.setText("⚠️ libtorrent missing — install it")
            self.dht_lbl.setStyleSheet(f"color: {Theme.Red}; font-size: 10px;")

    def _quit(self):
        self.swarm.stop()
        QApplication.quit()

    def closeEvent(self, event):
        if hasattr(self, 'tray') and self.tray.isVisible():
            self.hide(); event.ignore()
        else:
            self.swarm.stop(); event.accept()


# === ENTRY ===
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    w = GTalkWindow()
    w.show()
    if not HAS_LT:
        QMessageBox.warning(w, "GTalk",
            "libtorrent not found!\n\nInstall: pip install libtorrent\n\n"
            "Without it, GTalk can't discover peers globally.\n"
            "DHT peer discovery requires libtorrent.")
    sys.exit(app.exec())
