import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/foundation.dart';
import '../models/message.dart';
import 'dht_service.dart';

/// Manages P2P connections to other GTalk users.
/// Combines DHT discovery + TCP messaging.
class PeerService extends ChangeNotifier {
  static const chatPort = 31337;

  String username;
  final List<Peer> peers = [];
  final Map<String, Socket> _sockets = {};
  final Set<String> _connecting = {};

  late DhtService _dht;
  ServerSocket? _server;
  bool _running = false;

  final StreamController<ChatMessage> _messageController = StreamController.broadcast();
  Stream<ChatMessage> get messages => _messageController.stream;

  int get onlineCount => peers.length;
  int get dhtNodes => _dht.dhtNodeCount;

  PeerService({required this.username});

  Future<void> start() async {
    _running = true;

    // Add firewall exception on Windows (best-effort, may need admin)
    if (Platform.isWindows) {
      try {
        await Process.run('netsh', [
          'advfirewall', 'firewall', 'add', 'rule',
          'name=GTalk', 'dir=in', 'action=allow', 'protocol=UDP',
          'localport=${chatPort + 1000}',
        ]);
        await Process.run('netsh', [
          'advfirewall', 'firewall', 'add', 'rule',
          'name=GTalk TCP', 'dir=in', 'action=allow', 'protocol=TCP',
          'localport=$chatPort',
        ]);
      } catch (_) {}
    }

    // Start TCP listener
    _server = await ServerSocket.bind(InternetAddress.anyIPv4, chatPort);
    _server!.listen(_handleIncoming);

    // Start DHT discovery
    _dht = DhtService(port: chatPort, onPeerFound: _onDhtPeerFound);
    await _dht.start();

    notifyListeners();
  }

  void _onDhtPeerFound(String ip, int port) {
    final addr = '$ip:$port';
    if (_sockets.containsKey(addr) || _connecting.contains(addr)) return;
    if (_isLocalIp(ip)) return;
    _connectTo(ip, port);
  }

  Future<void> _connectTo(String ip, int port) async {
    final addr = '$ip:$port';
    _connecting.add(addr);
    try {
      final socket = await Socket.connect(ip, port,
        timeout: const Duration(seconds: 5));
      await _handshake(socket, addr, true);
    } catch (_) {
    } finally {
      _connecting.remove(addr);
    }
  }

  void _handleIncoming(Socket socket) {
    final addr = '${socket.remoteAddress.address}:${socket.remotePort}';
    _handshake(socket, addr, false);
  }

  Future<void> _handshake(Socket socket, String addr, bool isOutgoing) async {
    try {
      // Send hello
      _sendFrame(socket, {'type': 'hello', 'username': username});

      // Wait for hello response
      final data = await socket.first.timeout(const Duration(seconds: 5));
      final msg = _parseFrame(data);
      if (msg == null || msg['type'] != 'hello') {
        socket.destroy();
        return;
      }

      final peerName = msg['username'] ?? addr;

      // Check if already connected
      if (_sockets.containsKey(addr)) {
        socket.destroy();
        return;
      }

      _sockets[addr] = socket;
      peers.add(Peer(username: peerName, address: addr));
      notifyListeners();

      // Listen for messages
      socket.listen(
        (data) => _onData(data, peerName, addr),
        onDone: () => _removePeer(addr),
        onError: (_) => _removePeer(addr),
      );
    } catch (_) {
      socket.destroy();
    }
  }

  void _onData(Uint8List data, String peerName, String addr) {
    final msg = _parseFrame(data);
    if (msg == null) return;

    final type = msg['type'];
    if (type == 'message' || type == 'dm') {
      final channel = type == 'dm' ? 'dm:${msg['sender'] ?? peerName}' : 'global';
      _messageController.add(ChatMessage(
        id: msg['id'] ?? DateTime.now().millisecondsSinceEpoch.toString(),
        sender: msg['sender'] ?? peerName,
        text: msg['text'] ?? '',
        timestamp: msg['timestamp'] ?? '',
        channel: channel,
        isOwn: false,
      ));
    }
  }

  void sendToGlobal(String text) {
    final msg = {
      'type': 'message', 'sender': username, 'text': text,
      'timestamp': _now(), 'channel': 'global',
      'id': DateTime.now().millisecondsSinceEpoch.toString(),
    };
    for (final socket in _sockets.values) {
      try { _sendFrame(socket, msg); } catch (_) {}
    }
  }

  void sendDm(String targetUsername, String text) {
    final msg = {
      'type': 'dm', 'sender': username, 'text': text,
      'timestamp': _now(),
      'id': DateTime.now().millisecondsSinceEpoch.toString(),
    };
    for (final peer in peers) {
      if (peer.username == targetUsername) {
        final socket = _sockets[peer.address];
        if (socket != null) {
          try { _sendFrame(socket, msg); } catch (_) {}
        }
        break;
      }
    }
  }

  void _removePeer(String addr) {
    _sockets.remove(addr)?.destroy();
    peers.removeWhere((p) => p.address == addr);
    notifyListeners();
  }

  void _sendFrame(Socket socket, Map<String, dynamic> data) {
    final json = utf8.encode(jsonEncode(data) + '\n');
    socket.add(json);
  }

  Map<String, dynamic>? _parseFrame(Uint8List data) {
    try {
      final str = utf8.decode(data).trim();
      // May contain multiple frames; take first
      final line = str.split('\n').first;
      return jsonDecode(line) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }

  String _now() => '${DateTime.now().hour.toString().padLeft(2, '0')}:${DateTime.now().minute.toString().padLeft(2, '0')}';

  bool _isLocalIp(String ip) {
    return ip == '127.0.0.1' || ip.startsWith('0.');
  }

  void stop() {
    _running = false;
    _dht.stop();
    _server?.close();
    for (final s in _sockets.values) s.destroy();
    _sockets.clear();
    peers.clear();
  }
}
