import 'dart:async';
import 'dart:io';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

/// DHT peer discovery using BitTorrent BEP-5 protocol over UDP.
/// Uses raw bytes for bencode (not strings) to handle binary node IDs correctly.
class DhtService {
  // SHA1("GTalk-Global-Chat-v2") — our swarm identifier
  static final Uint8List gtalkInfoHash = _sha1(utf8.encode('GTalk-Global-Chat-v2'));

  final int port;
  final void Function(String ip, int port) onPeerFound;

  RawDatagramSocket? _socket;
  bool _running = false;
  final Set<String> _knownPeers = {};
  final List<_DhtNode> _routingTable = [];
  late final Uint8List _nodeId;
  int _dhtNodes = 0;

  static const _bootstrapNodes = [
    ('dht.transmissionbt.com', 6881),
    ('router.utorrent.com', 6881),
    ('router.bittorrent.com', 6881),
    ('dht.libtorrent.org', 25401),
  ];

  DhtService({required this.port, required this.onPeerFound}) {
    final rng = Random.secure();
    _nodeId = Uint8List.fromList(List.generate(20, (_) => rng.nextInt(256)));
  }

  int get dhtNodeCount => _dhtNodes;

  Future<void> start() async {
    _running = true;
    try {
      _socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, port + 1000);
    } catch (_) {
      // Port in use — try random
      _socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);
    }
    _socket!.listen(_handleDatagram);

    // Bootstrap
    _bootstrap();

    // Periodic operations
    Timer.periodic(const Duration(seconds: 10), (_) {
      if (!_running) return;
      _searchPeers();
    });
    Timer.periodic(const Duration(seconds: 60), (_) {
      if (!_running) return;
      _bootstrap(); // Re-bootstrap periodically
    });

    // Initial search after bootstrap
    Future.delayed(const Duration(seconds: 3), _searchPeers);
    Future.delayed(const Duration(seconds: 8), _searchPeers);
  }

  void stop() {
    _running = false;
    _socket?.close();
  }

  void _bootstrap() {
    for (final (host, port) in _bootstrapNodes) {
      _sendFindNode(host, port, _nodeId);
    }
  }

  void _searchPeers() {
    // Query routing table nodes for our info_hash
    final nodes = _routingTable.take(8).toList();
    for (final node in nodes) {
      _sendGetPeers(node.ip, node.port);
    }
    // Also query bootstrap nodes directly
    for (final (host, port) in _bootstrapNodes.take(2)) {
      _sendGetPeers(host, port);
    }
  }

  void _sendFindNode(String host, int port, Uint8List target) {
    final txId = _randomBytes(2);
    final msg = _buildFindNode(txId, target);
    _sendToHost(host, port, msg);
  }

  void _sendGetPeers(String host, int port) {
    final txId = _randomBytes(2);
    final msg = _buildGetPeers(txId);
    _sendToHost(host, port, msg);
  }

  void _sendToHost(String host, int port, Uint8List data) {
    InternetAddress.lookup(host).then((addrs) {
      if (addrs.isNotEmpty && _socket != null) {
        _socket!.send(data, addrs.first, port);
      }
    }).catchError((_) {});
  }

  void _handleDatagram(RawSocketEvent event) {
    if (event != RawSocketEvent.read) return;
    final dg = _socket?.receive();
    if (dg == null) return;

    try {
      final decoded = _bdecodeFull(dg.data);
      if (decoded == null || decoded is! Map) return;

      final r = decoded['r'];
      if (r == null || r is! Map) return;

      // Parse compact nodes (26 bytes each: 20 id + 4 ip + 2 port)
      final nodesData = r['nodes'];
      if (nodesData != null && nodesData is Uint8List) {
        for (var i = 0; i + 26 <= nodesData.length; i += 26) {
          final ip = '${nodesData[i + 20]}.${nodesData[i + 21]}.${nodesData[i + 22]}.${nodesData[i + 23]}';
          final p = (nodesData[i + 24] << 8) | nodesData[i + 25];
          if (p > 0 && p < 65536 && ip != '0.0.0.0') {
            _routingTable.add(_DhtNode(ip, p));
          }
        }
        if (_routingTable.length > 300) {
          _routingTable.removeRange(0, _routingTable.length - 300);
        }
        _dhtNodes = _routingTable.length;
      }

      // Parse compact peers (6 bytes each: 4 ip + 2 port)
      final values = r['values'];
      if (values != null && values is List) {
        for (final v in values) {
          if (v is Uint8List && v.length >= 6) {
            final ip = '${v[0]}.${v[1]}.${v[2]}.${v[3]}';
            final p = (v[4] << 8) | v[5];
            final key = '$ip:$p';
            if (!_knownPeers.contains(key) && p > 0) {
              _knownPeers.add(key);
              onPeerFound(ip, p);
            }
          }
        }
      }
    } catch (_) {}
  }

  // === BENCODE BUILDER (byte-level, handles binary correctly) ===

  Uint8List _buildFindNode(Uint8List txId, Uint8List target) {
    // d1:ad2:id20:<nodeId>6:target20:<target>e1:q9:find_node1:t2:<txId>1:y1:qe
    final buf = BytesBuilder();
    buf.add(utf8.encode('d'));
    buf.add(utf8.encode('1:a'));
    buf.add(utf8.encode('d'));
    buf.add(utf8.encode('2:id')); buf.add(utf8.encode('20:')); buf.add(_nodeId);
    buf.add(utf8.encode('6:target')); buf.add(utf8.encode('20:')); buf.add(target);
    buf.add(utf8.encode('e'));
    buf.add(utf8.encode('1:q')); buf.add(utf8.encode('9:find_node'));
    buf.add(utf8.encode('1:t')); buf.add(utf8.encode('2:')); buf.add(txId);
    buf.add(utf8.encode('1:y')); buf.add(utf8.encode('1:q'));
    buf.add(utf8.encode('e'));
    return buf.toBytes();
  }

  Uint8List _buildGetPeers(Uint8List txId) {
    // d1:ad2:id20:<nodeId>9:info_hash20:<hash>e1:q9:get_peers1:t2:<txId>1:y1:qe
    final buf = BytesBuilder();
    buf.add(utf8.encode('d'));
    buf.add(utf8.encode('1:a'));
    buf.add(utf8.encode('d'));
    buf.add(utf8.encode('2:id')); buf.add(utf8.encode('20:')); buf.add(_nodeId);
    buf.add(utf8.encode('9:info_hash')); buf.add(utf8.encode('20:')); buf.add(gtalkInfoHash);
    buf.add(utf8.encode('e'));
    buf.add(utf8.encode('1:q')); buf.add(utf8.encode('9:get_peers'));
    buf.add(utf8.encode('1:t')); buf.add(utf8.encode('2:')); buf.add(txId);
    buf.add(utf8.encode('1:y')); buf.add(utf8.encode('1:q'));
    buf.add(utf8.encode('e'));
    return buf.toBytes();
  }

  // === BENCODE DECODER (byte-level) ===

  dynamic _bdecodeFull(Uint8List data) {
    try {
      final result = _bdecodeAt(data, 0);
      return result?.value;
    } catch (_) {
      return null;
    }
  }

  _BResult? _bdecodeAt(Uint8List data, int pos) {
    if (pos >= data.length) return null;
    final b = data[pos];

    if (b == 0x64) { // 'd' - dictionary
      pos++;
      final map = <String, dynamic>{};
      while (pos < data.length && data[pos] != 0x65) { // 'e'
        final keyResult = _bdecodeAt(data, pos);
        if (keyResult == null) break;
        pos = keyResult.end;
        final valResult = _bdecodeAt(data, pos);
        if (valResult == null) break;
        pos = valResult.end;
        final key = keyResult.value is Uint8List
            ? utf8.decode(keyResult.value as Uint8List, allowMalformed: true)
            : keyResult.value.toString();
        map[key] = valResult.value;
      }
      return _BResult(map, pos + 1);
    }

    if (b == 0x6C) { // 'l' - list
      pos++;
      final list = [];
      while (pos < data.length && data[pos] != 0x65) {
        final r = _bdecodeAt(data, pos);
        if (r == null) break;
        list.add(r.value);
        pos = r.end;
      }
      return _BResult(list, pos + 1);
    }

    if (b == 0x69) { // 'i' - integer
      pos++;
      final end = data.indexOf(0x65, pos); // 'e'
      if (end < 0) return null;
      final numStr = utf8.decode(data.sublist(pos, end));
      return _BResult(int.tryParse(numStr) ?? 0, end + 1);
    }

    // String/bytes: <length>:<data>
    if (b >= 0x30 && b <= 0x39) { // '0'-'9'
      final colonIdx = data.indexOf(0x3A, pos); // ':'
      if (colonIdx < 0) return null;
      final lenStr = utf8.decode(data.sublist(pos, colonIdx));
      final len = int.tryParse(lenStr) ?? 0;
      final start = colonIdx + 1;
      if (start + len > data.length) return null;
      // Return as Uint8List (preserves binary data like node IDs)
      return _BResult(Uint8List.fromList(data.sublist(start, start + len)), start + len);
    }

    return null;
  }

  Uint8List _randomBytes(int n) =>
      Uint8List.fromList(List.generate(n, (_) => Random().nextInt(256)));

  /// Simple SHA1 implementation for the info_hash
  static Uint8List _sha1(List<int> input) {
    // Use Dart's built-in (available in dart:convert ecosystem)
    // Minimal SHA1 for just generating our fixed hash
    var h0 = 0x67452301;
    var h1 = 0xEFCDAB89;
    var h2 = 0x98BADCFE;
    var h3 = 0x10325476;
    var h4 = 0xC3D2E1F0;

    final data = Uint8List.fromList(input);
    final bitLen = data.length * 8;

    // Padding
    final padded = BytesBuilder();
    padded.add(data);
    padded.addByte(0x80);
    while ((padded.length % 64) != 56) padded.addByte(0);
    padded.add(Uint8List(8)
      ..[0] = (bitLen >> 56) & 0xFF
      ..[1] = (bitLen >> 48) & 0xFF
      ..[2] = (bitLen >> 40) & 0xFF
      ..[3] = (bitLen >> 32) & 0xFF
      ..[4] = (bitLen >> 24) & 0xFF
      ..[5] = (bitLen >> 16) & 0xFF
      ..[6] = (bitLen >> 8) & 0xFF
      ..[7] = bitLen & 0xFF);

    final msg = padded.toBytes();
    for (var chunk = 0; chunk < msg.length; chunk += 64) {
      final w = List<int>.filled(80, 0);
      for (var i = 0; i < 16; i++) {
        w[i] = (msg[chunk + i * 4] << 24) | (msg[chunk + i * 4 + 1] << 16) |
               (msg[chunk + i * 4 + 2] << 8) | msg[chunk + i * 4 + 3];
      }
      for (var i = 16; i < 80; i++) {
        w[i] = _rotl(w[i-3] ^ w[i-8] ^ w[i-14] ^ w[i-16], 1);
      }

      var a = h0, b = h1, c = h2, d = h3, e = h4;
      for (var i = 0; i < 80; i++) {
        int f, k;
        if (i < 20) { f = (b & c) | ((~b) & d); k = 0x5A827999; }
        else if (i < 40) { f = b ^ c ^ d; k = 0x6ED9EBA1; }
        else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8F1BBCDC; }
        else { f = b ^ c ^ d; k = 0xCA62C1D6; }

        final temp = (_rotl(a, 5) + f + e + k + w[i]) & 0xFFFFFFFF;
        e = d; d = c; c = _rotl(b, 30); b = a; a = temp;
      }
      h0 = (h0 + a) & 0xFFFFFFFF;
      h1 = (h1 + b) & 0xFFFFFFFF;
      h2 = (h2 + c) & 0xFFFFFFFF;
      h3 = (h3 + d) & 0xFFFFFFFF;
      h4 = (h4 + e) & 0xFFFFFFFF;
    }

    final result = Uint8List(20);
    for (var i = 0; i < 4; i++) {
      result[i] = (h0 >> (24 - i * 8)) & 0xFF;
      result[i + 4] = (h1 >> (24 - i * 8)) & 0xFF;
      result[i + 8] = (h2 >> (24 - i * 8)) & 0xFF;
      result[i + 12] = (h3 >> (24 - i * 8)) & 0xFF;
      result[i + 16] = (h4 >> (24 - i * 8)) & 0xFF;
    }
    return result;
  }

  static int _rotl(int n, int bits) => ((n << bits) | (n >> (32 - bits))) & 0xFFFFFFFF;
}

class _BResult {
  final dynamic value;
  final int end;
  _BResult(this.value, this.end);
}

class _DhtNode {
  final String ip;
  final int port;
  _DhtNode(this.ip, this.port);
}
