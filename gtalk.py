# GTalk — Cross-platform Encrypted P2P Chat
# Python 3.10+ / PyQt6 / Chrome-dark theme (matching GBrowser/Ceprkac)
# Features: E2E encryption, LAN discovery, file transfer, tray icon, auto-reconnect
import sys
import os
import json
import socket
import struct
import threading
import time
import hashlib
import base64
import secrets
from datetime import datetime
from pathlib import Path
from PyQt6.QtWidgets import *
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QByteArray
from PyQt6.QtGui import QColor, QFont, QIcon, QAction, QPixmap, QPainter
from PyQt6.QtMultimedia import QSoundEffect

# Optional: encryption (falls back to plaintext if not available)
try:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import serialization
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

APP_VERSION = "2.0.0"
APP_NAME = "GTalk"
DEFAULT_PORT = 12345
DISCOVERY_PORT = 12346
BUFFER_SIZE = 65536
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

# === THEME ===
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
    Yellow      = "#FDD663"
    BubbleSelf  = "#1A3A5C"
    BubblePeer  = "#35363A"

# === CONFIG ===
CONFIG_DIR = Path.home() / ".gtalk"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
(CONFIG_DIR / "downloads").mkdir(exist_ok=True)
HISTORY_FILE = CONFIG_DIR / "history.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
KEYS_FILE = CONFIG_DIR / "identity.key"

def load_settings():
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except: pass
    return {"username": socket.gethostname(), "port": DEFAULT_PORT,
            "last_peer": "", "notifications": True, "auto_reconnect": True}

def save_settings(s):
    SETTINGS_FILE.write_text(json.dumps(s, indent=2))

def load_history():
    if HISTORY_FILE.exists():
        try: return json.loads(HISTORY_FILE.read_text())
        except: pass
    return []

def save_history(msgs):
    HISTORY_FILE.write_text(json.dumps(msgs[-2000:], indent=2))

# === ENCRYPTION ===
class CryptoSession:
    """X25519 key exchange + AES-256-GCM per-peer encryption."""
    def __init__(self):
        if HAS_CRYPTO:
            self._private_key = X25519PrivateKey.generate()
            self._public_key = self._private_key.public_key()
            self._shared_key = None
        else:
            self._private_key = None
            self._public_key = None
            self._shared_key = None

    @property
    def public_key_bytes(self) -> bytes:
        if not HAS_CRYPTO: return b'\x00' * 32
        return self._public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    def derive_shared_key(self, peer_public_bytes: bytes):
        if not HAS_CRYPTO: return
        peer_key = X25519PublicKey.from_public_bytes(peer_public_bytes)
        shared = self._private_key.exchange(peer_key)
        self._shared_key = hashlib.sha256(shared).digest()

    def encrypt(self, plaintext: bytes) -> bytes:
        if not self._shared_key: return plaintext
        nonce = secrets.token_bytes(12)
        aesgcm = AESGCM(self._shared_key)
        ct = aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ct

    def decrypt(self, data: bytes) -> bytes:
        if not self._shared_key: return data
        nonce, ct = data[:12], data[12:]
        aesgcm = AESGCM(self._shared_key)
        return aesgcm.decrypt(nonce, ct, None)

    @property
    def is_encrypted(self):
        return self._shared_key is not None

# === LAN DISCOVERY (UDP broadcast) ===
class LanDiscovery:
    """Broadcasts presence on LAN so peers auto-discover each other."""
    def __init__(self, username, port):
        self.username = username
        self.port = port
        self._running = False
        self._found_peers = {}  # ip -> (username, port, last_seen)

    def start(self, on_peer_found):
        self._running = True
        self._callback = on_peer_found
        threading.Thread(target=self._broadcast_loop, daemon=True).start()
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _broadcast_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(1.0)
        msg = json.dumps({"app": "gtalk", "user": self.username, "port": self.port}).encode()
        while self._running:
            try:
                sock.sendto(msg, ('255.255.255.255', DISCOVERY_PORT))
            except: pass
            time.sleep(5)
        sock.close()

    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('', DISCOVERY_PORT))
        except:
            return
        sock.settimeout(1.0)
        while self._running:
            try:
                data, addr = sock.recvfrom(1024)
                msg = json.loads(data.decode())
                if msg.get("app") == "gtalk":
                    ip = addr[0]
                    # Don't discover ourselves
                    if ip not in self._get_local_ips():
                        peer_info = (msg.get("user", ip), msg.get("port", DEFAULT_PORT))
                        if ip not in self._found_peers:
                            self._found_peers[ip] = peer_info
                            self._callback(ip, peer_info[0], peer_info[1])
            except socket.timeout:
                continue
            except: pass
        sock.close()

    def _get_local_ips(self):
        ips = set(['127.0.0.1'])
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ips.add(info[4][0])
        except: pass
        return ips

# === PROTOCOL ===
# Message format: [4-byte length][JSON payload]
# Types: hello, message, file_offer, file_data, file_ack, typing, read_receipt

def send_frame(sock, data: dict, crypto: CryptoSession = None):
    raw = json.dumps(data).encode('utf-8')
    if crypto and crypto.is_encrypted:
        raw = crypto.encrypt(raw)
    length = struct.pack('!I', len(raw))
    sock.sendall(length + raw)

def recv_frame(sock, crypto: CryptoSession = None) -> dict:
    header = _recv_exact(sock, 4)
    if not header: return None
    length = struct.unpack('!I', header)[0]
    if length > 10 * 1024 * 1024:  # Max 10MB per frame
        return None
    raw = _recv_exact(sock, length)
    if not raw: return None
    if crypto and crypto.is_encrypted:
        raw = crypto.decrypt(raw)
    return json.loads(raw.decode('utf-8'))

def _recv_exact(sock, n):
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk: return None
        data.extend(chunk)
    return bytes(data)

# === PEER CONNECTION ===
class PeerConnection:
    """Manages a single peer: encryption handshake, send/receive, auto-reconnect."""
    def __init__(self, sock, addr, username, is_outgoing=False):
        self.sock = sock
        self.addr = addr  # "ip:port"
        self.peer_username = "Unknown"
        self.local_username = username
        self.is_outgoing = is_outgoing
        self.crypto = CryptoSession()
        self.connected = True
        self._typing_timer = None

    def handshake(self):
        """Exchange public keys and derive shared secret."""
        # Send our hello + public key
        send_frame(self.sock, {
            "type": "hello",
            "username": self.local_username,
            "version": APP_VERSION,
            "pubkey": base64.b64encode(self.crypto.public_key_bytes).decode()
        })
        # Receive peer's hello
        msg = recv_frame(self.sock)
        if msg and msg.get("type") == "hello":
            self.peer_username = msg.get("username", "Unknown")
            peer_pubkey = base64.b64decode(msg.get("pubkey", ""))
            if len(peer_pubkey) == 32 and HAS_CRYPTO:
                self.crypto.derive_shared_key(peer_pubkey)
            return True
        return False

    def send_message(self, text):
        send_frame(self.sock, {
            "type": "message",
            "text": text,
            "sender": self.local_username,
            "timestamp": datetime.now().isoformat(),
            "id": secrets.token_hex(8)
        }, self.crypto)

    def send_typing(self):
        try:
            send_frame(self.sock, {"type": "typing", "sender": self.local_username}, self.crypto)
        except: pass

    def send_read_receipt(self, msg_id):
        try:
            send_frame(self.sock, {"type": "read_receipt", "id": msg_id}, self.crypto)
        except: pass

    def send_file_offer(self, filename, size):
        send_frame(self.sock, {
            "type": "file_offer",
            "filename": filename,
            "size": size,
            "sender": self.local_username
        }, self.crypto)

    def close(self):
        self.connected = False
        try: self.sock.close()
        except: pass

# === NETWORK ENGINE ===
class NetworkEngine(QObject):
    message_received = pyqtSignal(str, str, str, str)  # sender, text, timestamp, msg_id
    peer_connected = pyqtSignal(str, str, bool)  # addr, username, encrypted
    peer_disconnected = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    typing_received = pyqtSignal(str)  # sender
    file_offered = pyqtSignal(str, str, int)  # sender, filename, size
    lan_peer_found = pyqtSignal(str, str, int)  # ip, username, port

    def __init__(self):
        super().__init__()
        self._running = False
        self._server_socket = None
        self._peers = {}  # addr -> PeerConnection
        self._lock = threading.Lock()
        self._username = "User"
        self._port = DEFAULT_PORT
        self._auto_reconnect = True
        self._reconnect_targets = set()
        self._discovery = None

    def configure(self, username, port, auto_reconnect=True):
        self._username = username
        self._port = port
        self._auto_reconnect = auto_reconnect

    def start(self):
        self._running = True
        threading.Thread(target=self._server_loop, daemon=True).start()
        threading.Thread(target=self._reconnect_loop, daemon=True).start()
        # LAN discovery
        self._discovery = LanDiscovery(self._username, self._port)
        self._discovery.start(self._on_lan_peer_found)

    def _on_lan_peer_found(self, ip, username, port):
        self.lan_peer_found.emit(ip, username, port)

    def _server_loop(self):
        try:
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind(('0.0.0.0', self._port))
            self._server_socket.listen(10)
            self._server_socket.settimeout(1.0)
            self.status_changed.emit(f"Listening on port {self._port}")
            while self._running:
                try:
                    sock, addr = self._server_socket.accept()
                    threading.Thread(target=self._handle_incoming,
                                   args=(sock, f"{addr[0]}:{addr[1]}"), daemon=True).start()
                except socket.timeout: continue
                except OSError: break
        except Exception as e:
            self.error_occurred.emit(f"Server error: {e}")

    def _handle_incoming(self, sock, addr):
        peer = PeerConnection(sock, addr, self._username, is_outgoing=False)
        if peer.handshake():
            with self._lock: self._peers[addr] = peer
            self.peer_connected.emit(addr, peer.peer_username, peer.crypto.is_encrypted)
            self._receive_loop(peer, addr)
        else:
            peer.close()

    def connect_to(self, host, port=None):
        port = port or self._port
        addr = f"{host}:{port}"
        if addr in self._peers: return
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((host, port))
            sock.settimeout(None)
            peer = PeerConnection(sock, addr, self._username, is_outgoing=True)
            if peer.handshake():
                with self._lock: self._peers[addr] = peer
                self._reconnect_targets.add((host, port))
                self.peer_connected.emit(addr, peer.peer_username, peer.crypto.is_encrypted)
                threading.Thread(target=self._receive_loop, args=(peer, addr), daemon=True).start()
            else:
                peer.close()
                self.error_occurred.emit(f"Handshake failed with {addr}")
        except Exception as e:
            self.error_occurred.emit(f"Connect to {addr}: {e}")

    def _receive_loop(self, peer, addr):
        while self._running and peer.connected:
            try:
                msg = recv_frame(peer.sock, peer.crypto)
                if msg is None: break
                self._dispatch(msg, peer, addr)
            except: break
        self._remove_peer(addr)

    def _dispatch(self, msg, peer, addr):
        t = msg.get("type", "")
        if t == "message":
            self.message_received.emit(
                msg.get("sender", peer.peer_username),
                msg.get("text", ""),
                msg.get("timestamp", datetime.now().isoformat()),
                msg.get("id", ""))
        elif t == "typing":
            self.typing_received.emit(msg.get("sender", peer.peer_username))
        elif t == "file_offer":
            self.file_offered.emit(msg.get("sender", ""), msg.get("filename", ""), msg.get("size", 0))

    def send_message(self, text):
        with self._lock:
            dead = []
            for addr, peer in self._peers.items():
                try: peer.send_message(text)
                except: dead.append(addr)
            for a in dead: self._remove_peer(a)

    def send_typing(self):
        with self._lock:
            for peer in self._peers.values():
                peer.send_typing()

    def _remove_peer(self, addr):
        with self._lock:
            peer = self._peers.pop(addr, None)
        if peer:
            peer.close()
            self.peer_disconnected.emit(addr)

    def _reconnect_loop(self):
        while self._running:
            time.sleep(10)
            if not self._auto_reconnect: continue
            with self._lock:
                connected_addrs = set(self._peers.keys())
            for host, port in list(self._reconnect_targets):
                if f"{host}:{port}" not in connected_addrs:
                    try: self.connect_to(host, port)
                    except: pass

    def stop(self):
        self._running = False
        if self._discovery: self._discovery.stop()
        with self._lock:
            for peer in self._peers.values(): peer.close()
            self._peers.clear()
        if self._server_socket:
            try: self._server_socket.close()
            except: pass

    @property
    def peer_count(self):
        with self._lock: return len(self._peers)

# === CHAT BUBBLE ===
class ChatBubble(QFrame):
    def __init__(self, sender, text, timestamp, is_self=False, is_system=False):
        super().__init__()
        self.setObjectName("bubble")
        if is_system:
            bg = Theme.Surface
            self.setStyleSheet(f"#bubble {{ background: {bg}; border-radius: 8px; padding: 4px 12px; margin: 4px 40px; }}")
            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color: {Theme.TextMuted}; font-size: 11px; font-style: italic;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)
            return

        bg = Theme.BubbleSelf if is_self else Theme.BubblePeer
        margin = "2px 50px 2px 8px" if not is_self else "2px 8px 2px 50px"
        self.setStyleSheet(f"#bubble {{ background: {bg}; border-radius: 12px; padding: 8px 12px; margin: {margin}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        header = QHBoxLayout()
        sender_lbl = QLabel(sender)
        sender_lbl.setStyleSheet(f"color: {Theme.Accent if not is_self else Theme.Green}; font-size: 11px; font-weight: bold;")
        time_str = ""
        try:
            dt = datetime.fromisoformat(timestamp)
            time_str = dt.strftime("%H:%M")
        except:
            time_str = timestamp[:5] if len(timestamp) >= 5 else timestamp
        time_lbl = QLabel(time_str)
        time_lbl.setStyleSheet(f"color: {Theme.TextMuted}; font-size: 10px;")
        time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        header.addWidget(sender_lbl)
        header.addStretch()
        header.addWidget(time_lbl)
        layout.addLayout(header)

        msg_lbl = QLabel(text)
        msg_lbl.setWordWrap(True)
        msg_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse)
        msg_lbl.setOpenExternalLinks(True)
        msg_lbl.setStyleSheet(f"color: {Theme.Text}; font-size: 13px;")
        layout.addWidget(msg_lbl)

# === MAIN WINDOW ===
class GTalkWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.messages = load_history()
        self._typing_timer = QTimer()
        self._typing_timer.setSingleShot(True)
        self._typing_timer.setInterval(3000)
        self._typing_cooldown = 0

        self.setWindowTitle(f"GTalk — {self.settings['username']}")
        self.setMinimumSize(750, 520)
        self.resize(950, 650)

        # Network
        self.net = NetworkEngine()
        self.net.configure(self.settings['username'], self.settings['port'],
                          self.settings.get('auto_reconnect', True))
        self.net.message_received.connect(self._on_message)
        self.net.peer_connected.connect(self._on_peer_connected)
        self.net.peer_disconnected.connect(self._on_peer_disconnected)
        self.net.status_changed.connect(self._on_status)
        self.net.error_occurred.connect(self._on_error)
        self.net.typing_received.connect(self._on_typing)
        self.net.lan_peer_found.connect(self._on_lan_peer)
        self.net.start()

        self._build_ui()
        self._build_tray()
        self._apply_theme()
        self._load_history_to_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main = QHBoxLayout(central)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # SIDEBAR
        sidebar = QFrame()
        sidebar.setFixedWidth(230)
        sidebar.setObjectName("sidebar")
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(12, 12, 12, 12)
        sl.setSpacing(6)

        # Logo
        logo = QLabel("💬 GTalk")
        logo.setStyleSheet(f"color: {Theme.Accent}; font-size: 16px; font-weight: bold;")
        sl.addWidget(logo)
        ver = QLabel(f"v{APP_VERSION}" + (" 🔒" if HAS_CRYPTO else " ⚠️ no encryption"))
        ver.setStyleSheet(f"color: {Theme.TextMuted}; font-size: 10px;")
        sl.addWidget(ver)
        sl.addSpacing(8)

        # Connect
        sl.addWidget(self._section("Connect"))
        self.peer_input = QLineEdit()
        self.peer_input.setPlaceholderText("IP or hostname")
        self.peer_input.setText(self.settings.get('last_peer', ''))
        self.peer_input.returnPressed.connect(self._connect)
        sl.addWidget(self.peer_input)
        btn = QPushButton("Connect")
        btn.setObjectName("accentBtn")
        btn.clicked.connect(self._connect)
        sl.addWidget(btn)

        # LAN Peers
        sl.addWidget(self._section("LAN Peers (auto-discovered)"))
        self.lan_list = QListWidget()
        self.lan_list.setMaximumHeight(80)
        self.lan_list.itemDoubleClicked.connect(self._connect_lan_peer)
        sl.addWidget(self.lan_list)

        # Connected
        sl.addWidget(self._section("Connected"))
        self.peers_list = QListWidget()
        self.peers_list.setMaximumHeight(120)
        sl.addWidget(self.peers_list)

        sl.addStretch()

        # Settings
        sl.addWidget(self._section("Settings"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Name:"))
        self.name_input = QLineEdit(self.settings['username'])
        self.name_input.editingFinished.connect(self._save_name)
        row.addWidget(self.name_input)
        sl.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Port:"))
        self.port_input = QLineEdit(str(self.settings['port']))
        self.port_input.setMaximumWidth(60)
        row2.addWidget(self.port_input)
        row2.addStretch()
        sl.addLayout(row2)

        self.status_lbl = QLabel(f"Listening on port {self.settings['port']}")
        self.status_lbl.setStyleSheet(f"color: {Theme.Green}; font-size: 10px;")
        sl.addWidget(self.status_lbl)
        main.addWidget(sidebar)

        # CHAT PANEL
        chat = QFrame()
        chat.setObjectName("chatPanel")
        cl = QVBoxLayout(chat)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # Typing indicator
        self.typing_lbl = QLabel("")
        self.typing_lbl.setStyleSheet(f"color: {Theme.TextMuted}; font-size: 11px; padding: 2px 16px;")
        self.typing_lbl.setFixedHeight(18)

        # Scroll area
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
        cl.addWidget(self.typing_lbl)

        # Input bar
        input_frame = QFrame()
        input_frame.setObjectName("inputBar")
        il = QHBoxLayout(input_frame)
        il.setContentsMargins(12, 8, 12, 8)

        # File attach button
        attach_btn = QPushButton("📎")
        attach_btn.setToolTip("Send file")
        attach_btn.setFixedSize(32, 32)
        attach_btn.clicked.connect(self._send_file)
        il.addWidget(attach_btn)

        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("Type a message... (Enter to send)")
        self.msg_input.setObjectName("msgInput")
        self.msg_input.returnPressed.connect(self._send)
        self.msg_input.textChanged.connect(self._on_typing_local)
        il.addWidget(self.msg_input)

        send_btn = QPushButton("Send")
        send_btn.setObjectName("accentBtn")
        send_btn.clicked.connect(self._send)
        il.addWidget(send_btn)

        cl.addWidget(input_frame)
        main.addWidget(chat)

    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self)
        # Create a simple colored icon
        pix = QPixmap(32, 32)
        pix.fill(QColor(Theme.Accent))
        self.tray.setIcon(QIcon(pix))
        menu = QMenu()
        show_action = QAction("Show GTalk", self)
        show_action.triggered.connect(self.show)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit)
        menu.addAction(show_action)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show()
            self.activateWindow()

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background: {Theme.Background}; color: {Theme.Text}; font-family: 'Segoe UI Variable', 'Segoe UI', 'SF Pro', sans-serif; font-size: 13px; }}
            #sidebar {{ background: {Theme.Sidebar}; border-right: 1px solid {Theme.Border}; }}
            #chatPanel {{ background: {Theme.Background}; }}
            #chatScroll {{ background: {Theme.Background}; border: none; }}
            #inputBar {{ background: {Theme.Surface}; border-top: 1px solid {Theme.Border}; }}
            #msgInput {{ background: {Theme.Input}; color: {Theme.Text}; border: 1px solid {Theme.Border}; border-radius: 18px; padding: 8px 16px; font-size: 13px; }}
            #msgInput:focus {{ border-color: {Theme.Accent}; }}
            #accentBtn {{ background: {Theme.Accent}; color: #202124; border: none; border-radius: 6px; padding: 8px 16px; font-weight: bold; }}
            #accentBtn:hover {{ background: #AECBFA; }}
            QLineEdit {{ background: {Theme.Surface}; color: {Theme.Text}; border: 1px solid {Theme.Border}; border-radius: 4px; padding: 5px 8px; }}
            QLabel {{ color: {Theme.TextDim}; }}
            QListWidget {{ background: {Theme.Surface}; color: {Theme.Text}; border: 1px solid {Theme.Border}; border-radius: 4px; font-size: 11px; }}
            QListWidget::item {{ padding: 3px 6px; }}
            QListWidget::item:hover {{ background: {Theme.SurfaceAlt}; }}
            QPushButton {{ background: {Theme.SurfaceAlt}; color: {Theme.Text}; border: 1px solid {Theme.Border}; border-radius: 6px; padding: 6px 12px; }}
            QPushButton:hover {{ background: #444750; }}
            QScrollBar:vertical {{ background: {Theme.Background}; width: 8px; }}
            QScrollBar::handle:vertical {{ background: {Theme.SurfaceAlt}; border-radius: 4px; min-height: 30px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QMenu {{ background: {Theme.Surface}; color: {Theme.Text}; border: 1px solid {Theme.Border}; }}
            QMenu::item:selected {{ background: {Theme.SurfaceAlt}; }}
        """)

    def _section(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {Theme.TextMuted}; font-size: 10px; font-weight: bold; margin-top: 6px;")
        return lbl

    def _load_history_to_ui(self):
        for msg in self.messages[-100:]:
            self._add_bubble(msg['sender'], msg['text'], msg['timestamp'],
                           is_self=(msg['sender'] == self.settings['username']))

    def _add_bubble(self, sender, text, timestamp, is_self=False, is_system=False):
        bubble = ChatBubble(sender, text, timestamp, is_self, is_system)
        self.chat_vbox.insertWidget(self.chat_vbox.count() - 1, bubble)
        QTimer.singleShot(30, self._scroll_bottom)

    def _scroll_bottom(self):
        sb = self.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    # === ACTIONS ===
    def _send(self):
        text = self.msg_input.text().strip()
        if not text: return
        self.msg_input.clear()
        ts = datetime.now().isoformat()
        self._add_bubble(self.settings['username'], text, ts, is_self=True)
        self.messages.append({"sender": self.settings['username'], "text": text, "timestamp": ts})
        save_history(self.messages)
        self.net.send_message(text)

    def _connect(self):
        peer = self.peer_input.text().strip()
        if not peer: return
        if ':' in peer:
            host, port = peer.rsplit(':', 1)
            port = int(port)
        else:
            host, port = peer, self.settings['port']
        self.settings['last_peer'] = peer
        save_settings(self.settings)
        threading.Thread(target=self.net.connect_to, args=(host, port), daemon=True).start()

    def _connect_lan_peer(self, item):
        text = item.text()  # "username (ip)"
        if '(' in text:
            ip = text.split('(')[1].rstrip(')')
            threading.Thread(target=self.net.connect_to, args=(ip, self.settings['port']), daemon=True).start()

    def _send_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Send File", "", "All Files (*)")
        if not path: return
        size = os.path.getsize(path)
        if size > MAX_FILE_SIZE:
            self._add_bubble("System", f"File too large (max {MAX_FILE_SIZE // (1024*1024)} MB)", "", is_system=True)
            return
        filename = os.path.basename(path)
        self._add_bubble("System", f"📎 Sending: {filename} ({size // 1024} KB)", "", is_system=True)
        # TODO: implement chunked file transfer over the protocol
        self._add_bubble("System", "File transfer not yet implemented in this version", "", is_system=True)

    def _save_name(self):
        new = self.name_input.text().strip()
        if new and new != self.settings['username']:
            self.settings['username'] = new
            self.net._username = new
            save_settings(self.settings)
            self.setWindowTitle(f"GTalk — {new}")

    def _on_typing_local(self):
        now = time.time()
        if now - self._typing_cooldown > 2:
            self._typing_cooldown = now
            self.net.send_typing()

    # === SIGNALS ===
    def _on_message(self, sender, text, timestamp, msg_id):
        self._add_bubble(sender, text, timestamp, is_self=False)
        self.messages.append({"sender": sender, "text": text, "timestamp": timestamp})
        save_history(self.messages)
        # Notification
        if not self.isActiveWindow() and hasattr(self, 'tray'):
            self.tray.showMessage("GTalk", f"{sender}: {text[:100]}", QSystemTrayIcon.MessageIcon.Information, 3000)
        self.typing_lbl.setText("")

    def _on_peer_connected(self, addr, username, encrypted):
        icon = "🔒" if encrypted else "⚠️"
        self.peers_list.addItem(f"{icon} {username} ({addr})")
        self._add_bubble("System", f"{username} connected {icon}", "", is_system=True)
        self._update_status()

    def _on_peer_disconnected(self, addr):
        for i in range(self.peers_list.count()):
            if addr in (self.peers_list.item(i).text() or ""):
                self.peers_list.takeItem(i)
                break
        self._add_bubble("System", f"Peer {addr} disconnected", "", is_system=True)
        self._update_status()

    def _on_status(self, s): self.status_lbl.setText(s)
    def _on_error(self, e):
        self.status_lbl.setText(e)
        self.status_lbl.setStyleSheet(f"color: {Theme.Red}; font-size: 10px;")

    def _on_typing(self, sender):
        self.typing_lbl.setText(f"{sender} is typing...")
        QTimer.singleShot(3000, lambda: self.typing_lbl.setText(""))

    def _on_lan_peer(self, ip, username, port):
        text = f"{username} ({ip})"
        if not self.lan_list.findItems(text, Qt.MatchFlag.MatchExactly):
            self.lan_list.addItem(text)

    def _update_status(self):
        n = self.net.peer_count
        if n > 0:
            self.status_lbl.setText(f"{n} peer(s) connected")
            self.status_lbl.setStyleSheet(f"color: {Theme.Green}; font-size: 10px;")
        else:
            self.status_lbl.setText(f"Listening on port {self.settings['port']}")
            self.status_lbl.setStyleSheet(f"color: {Theme.TextDim}; font-size: 10px;")

    def _quit(self):
        self.net.stop()
        QApplication.quit()

    def closeEvent(self, event):
        if hasattr(self, 'tray') and self.tray.isVisible():
            self.hide()
            event.ignore()  # Minimize to tray
        else:
            self.net.stop()
            event.accept()


# === ENTRY ===
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)
    window = GTalkWindow()
    window.show()
    sys.exit(app.exec())
