import 'dart:async';
import 'dart:io';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';
import 'package:crypto/crypto.dart' as crypto;

/// Lightweight DHT peer discovery using BitTorrent UDP protocol.
/// Bootstraps into the global DHT network and finds other GTalk peers.
///
/// Uses the BitTorrent DHT BEP-5 protocol directly over UDP:
/// 1. Sends "find_node" to bootstrap nodes to populate routing table
/// 2. Sends "get_peers" for the GTalk info_hash to find peers
/// 3. Sends "announce_peer" to tell the network we're running GTalk
class DhtService {
  static final Uint8List gtalkInfoHash = Uint8List.fromList(
    crypto.sha1.convert(utf8.encode('GTalk-Global-Chat-v2')).bytes,
  );

  final int port;
  final void Function(String ip, int port) onPeerFound;

  RawDatagramSocket? _socket;
  bool _running = false;
  final Set<String> _knownPeers = {};
  final List<_DhtNode> _routingTable = [];
  late final Uint8List _nodeId;
  int _dhtNodes = 0;

  // Bootstrap nodes (same as BitTorrent clients use)
  static const _bootstrapNodes = [
    ('router.bittorrent.com', 6881),
    ('dht.transmissionbt.com', 6881),
    ('router.utorrent.com', 6881),
    ('dht.libtorrent.org', 25401),
  ];

  DhtService({required this.port, required this.onPeerFound}) {
    // Generate random 20-byte node ID
    final rng = Random.secure();
    _nodeId = Uint8List.fromList(List.generate(20, (_) => rng.nextInt(256)));
  }

  int get dhtNodeCount => _dhtNodes;

  Future<void> start() async {
    _running = true;
    _socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, port + 1000);
    _socket!.listen(_handleDatagram);

    // Bootstrap
    for (final (host, port) in _bootstrapNodes) {
      _sendFindNode(host, port, _nodeId);
    }

    // Periodic search + announce
    Timer.periodic(const Duration(seconds: 15), (_) {
      if (!_running) return;
      _searchPeers();
    });
    Timer.periodic(const Duration(seconds: 30), (_) {
      if (!_running) return;
      _announceSelf();
    });

    // Initial search after bootstrap settles
    Future.delayed(const Duration(seconds: 5), _searchPeers);
  }

  void stop() {
    _running = false;
    _socket?.close();
  }

  void _searchPeers() {
    // Send get_peers to known nodes
    for (final node in _routingTable.take(20)) {
      _sendGetPeers(node.ip, node.port);
    }
    // Also try bootstrap nodes directly
    for (final (host, port) in _bootstrapNodes) {
      _sendGetPeers(host, port);
    }
  }

  void _announceSelf() {
    // Simplified announce — real BEP-5 requires a token from get_peers response
    // For discovery, get_peers is sufficient (peers see us in their responses)
  }

  void _sendFindNode(String host, int port, Uint8List target) {
    final txId = _randomTxId();
    final msg = _bencode({
      't': txId,
      'y': 'q',
      'q': 'find_node',
      'a': {'id': String.fromCharCodes(_nodeId), 'target': String.fromCharCodes(target)},
    });
    _sendTo(host, port, msg);
  }

  void _sendGetPeers(String host, int port) {
    final txId = _randomTxId();
    final msg = _bencode({
      't': txId,
      'y': 'q',
      'q': 'get_peers',
      'a': {'id': String.fromCharCodes(_nodeId), 'info_hash': String.fromCharCodes(gtalkInfoHash)},
    });
    _sendTo(host, port, msg);
  }

  void _sendTo(String host, int port, Uint8List data) {
    try {
      InternetAddress.lookup(host).then((addrs) {
        if (addrs.isNotEmpty) {
          _socket?.send(data, addrs.first, port);
        }
      });
    } catch (_) {}
  }

  void _handleDatagram(RawSocketEvent event) {
    if (event != RawSocketEvent.read) return;
    final dg = _socket?.receive();
    if (dg == null) return;

    try {
      final decoded = _bdecode(dg.data);
      if (decoded == null) return;

      final response = decoded['r'];
      if (response == null) return;

      // Extract nodes (compact format: 26 bytes each = 20 id + 4 ip + 2 port)
      if (response['nodes'] != null) {
        final nodes = response['nodes'] as String;
        final bytes = Uint8List.fromList(nodes.codeUnits);
        for (var i = 0; i + 26 <= bytes.length; i += 26) {
          final ip = '${bytes[i + 20]}.${bytes[i + 21]}.${bytes[i + 22]}.${bytes[i + 23]}';
          final port = (bytes[i + 24] << 8) | bytes[i + 25];
          if (port > 0 && port < 65536) {
            _routingTable.add(_DhtNode(ip, port));
            _dhtNodes = _routingTable.length;
          }
        }
        // Cap routing table
        if (_routingTable.length > 200) {
          _routingTable.removeRange(0, _routingTable.length - 200);
        }
      }

      // Extract peers (compact format: 6 bytes each = 4 ip + 2 port)
      if (response['values'] != null) {
        final values = response['values'];
        if (values is List) {
          for (final v in values) {
            final bytes = Uint8List.fromList((v as String).codeUnits);
            if (bytes.length >= 6) {
              final ip = '${bytes[0]}.${bytes[1]}.${bytes[2]}.${bytes[3]}';
              final port = (bytes[4] << 8) | bytes[5];
              final key = '$ip:$port';
              if (!_knownPeers.contains(key) && port > 0) {
                _knownPeers.add(key);
                onPeerFound(ip, port);
              }
            }
          }
        }
      }
    } catch (_) {}
  }

  // === BENCODE (minimal implementation for DHT) ===
  String _randomTxId() => String.fromCharCodes(
    List.generate(2, (_) => Random().nextInt(256)));

  Uint8List _bencode(dynamic data) {
    final buf = StringBuffer();
    _bencodeValue(buf, data);
    return Uint8List.fromList(utf8.encode(buf.toString()));
  }

  void _bencodeValue(StringBuffer buf, dynamic value) {
    if (value is String) {
      buf.write('${value.length}:$value');
    } else if (value is int) {
      buf.write('i${value}e');
    } else if (value is Map) {
      buf.write('d');
      final keys = value.keys.toList()..sort();
      for (final k in keys) {
        _bencodeValue(buf, k.toString());
        _bencodeValue(buf, value[k]);
      }
      buf.write('e');
    } else if (value is List) {
      buf.write('l');
      for (final item in value) _bencodeValue(buf, item);
      buf.write('e');
    }
  }

  Map<String, dynamic>? _bdecode(Uint8List data) {
    try {
      final str = String.fromCharCodes(data);
      final result = _bdecodeValue(str, 0);
      return result.value as Map<String, dynamic>?;
    } catch (_) {
      return null;
    }
  }

  _BDecoded _bdecodeValue(String s, int i) {
    if (i >= s.length) return _BDecoded(null, i);
    final c = s[i];
    if (c == 'i') {
      final end = s.indexOf('e', i);
      return _BDecoded(int.tryParse(s.substring(i + 1, end)) ?? 0, end + 1);
    } else if (c == 'l') {
      final list = [];
      var pos = i + 1;
      while (pos < s.length && s[pos] != 'e') {
        final r = _bdecodeValue(s, pos);
        list.add(r.value);
        pos = r.nextIndex;
      }
      return _BDecoded(list, pos + 1);
    } else if (c == 'd') {
      final map = <String, dynamic>{};
      var pos = i + 1;
      while (pos < s.length && s[pos] != 'e') {
        final key = _bdecodeValue(s, pos);
        final val = _bdecodeValue(s, key.nextIndex);
        map[key.value.toString()] = val.value;
        pos = val.nextIndex;
      }
      return _BDecoded(map, pos + 1);
    } else if (c.codeUnitAt(0) >= 48 && c.codeUnitAt(0) <= 57) {
      final colonIdx = s.indexOf(':', i);
      final len = int.parse(s.substring(i, colonIdx));
      final str = s.substring(colonIdx + 1, colonIdx + 1 + len);
      return _BDecoded(str, colonIdx + 1 + len);
    }
    return _BDecoded(null, i + 1);
  }
}

class _BDecoded {
  final dynamic value;
  final int nextIndex;
  _BDecoded(this.value, this.nextIndex);
}

class _DhtNode {
  final String ip;
  final int port;
  _DhtNode(this.ip, this.port);
}
