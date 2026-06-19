import 'dart:async';
import 'dart:io';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';
import 'package:flutter/foundation.dart';

/// DHT peer discovery using BitTorrent BEP-5 protocol over UDP.
/// Uses raw bytes for bencode to handle binary node IDs correctly.
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

  // Resolved bootstrap addresses (IP-based, no DNS needed at send time)
  final List<_DhtNode> _bootstrapResolved = [];

  static const _bootstrapHosts = [
    ('router.bittorrent.com', 6881),
    ('router.utorrent.com', 6881),
    ('dht.transmissionbt.com', 6881),
    ('dht.libtorrent.org', 25401),
  ];

  // Hardcoded fallback IPs in case DNS fails
  static const _fallbackIps = [
    ('67.215.246.10', 6881),   // router.bittorrent.com
    ('82.221.103.244', 6881),  // router.utorrent.com
    ('212.129.33.50', 6881),   // dht.transmissionbt.com
  ];

  DhtService({required this.port, required this.onPeerFound}) {
    final rng = Random.secure();
    _nodeId = Uint8List.fromList(List.generate(20, (_) => rng.nextInt(256)));
  }

  int get dhtNodeCount => _dhtNodes;

  Future<void> start() async {
    _running = true;

    // Bind UDP socket
    try {
      _socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, port + 1000);
    } catch (_) {
      try {
        _socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);
      } catch (e) {
        debugPrint('DHT: Cannot bind UDP socket: $e');
        return;
      }
    }

    debugPrint('DHT: UDP socket bound on port ${_socket!.port}');

    // Explicitly configure socket for receiving
    _socket!.readEventsEnabled = true;
    _socket!.writeEventsEnabled = false;

    _socket!.listen(_onSocketEvent, onError: (e) {
      debugPrint('DHT: Socket error: $e');
    });

    // Resolve bootstrap nodes (with timeout so we don't hang)
    await _resolveBootstrapNodes();

    // Send initial find_node to all bootstrap nodes
    _sendBootstrapFindNodes();

    // Retry schedule
    _scheduleRetries();

    // Periodic maintenance
    Timer.periodic(const Duration(seconds: 15), (_) {
      if (!_running) return;
      _searchPeers();
    });
    Timer.periodic(const Duration(seconds: 60), (_) {
      if (!_running) return;
      _sendBootstrapFindNodes();
    });
  }

  void stop() {
    _running = false;
    _socket?.close();
  }

  /// Resolve DNS for bootstrap nodes ahead of time.
  Future<void> _resolveBootstrapNodes() async {
    // Always add fallback IPs first (guaranteed to work without DNS)
    for (final (ip, port) in _fallbackIps) {
      _bootstrapResolved.add(_DhtNode(ip, port));
    }

    // Try resolving hostnames
    for (final (host, port) in _bootstrapHosts) {
      try {
        final addrs = await InternetAddress.lookup(host, type: InternetAddressType.IPv4)
            .timeout(const Duration(seconds: 3));
        if (addrs.isNotEmpty) {
          final ip = addrs.first.address;
          _bootstrapResolved.add(_DhtNode(ip, port));
          debugPrint('DHT: Resolved $host -> $ip');
        }
      } catch (e) {
        debugPrint('DHT: DNS failed for $host: $e');
      }
    }

    debugPrint('DHT: ${_bootstrapResolved.length} bootstrap endpoints ready');
  }

  void _scheduleRetries() {
    for (final delay in [2, 5, 10, 20]) {
      Timer(Duration(seconds: delay), () {
        if (!_running) return;
        if (_dhtNodes == 0) {
          debugPrint('DHT: Still 0 nodes after ${delay}s, retrying...');
          _sendBootstrapFindNodes();
        } else {
          _searchPeers();
        }
      });
    }
  }

  /// Send find_node to all resolved bootstrap nodes using direct IPs.
  void _sendBootstrapFindNodes() {
    for (final node in _bootstrapResolved) {
      _sendFindNodeDirect(node.ip, node.port, _nodeId);
    }
  }

  void _searchPeers() {
    // Query routing table nodes for peers with our info_hash
    final nodes = _routingTable.take(16).toList();
    for (final node in nodes) {
      _sendGetPeersDirect(node.ip, node.port);
    }
    // Also hit bootstrap nodes with get_peers
    for (final node in _bootstrapResolved.take(3)) {
      _sendGetPeersDirect(node.ip, node.port);
    }
  }

  void _sendFindNodeDirect(String ip, int port, Uint8List target) {
    final msg = _encodeFindNode(target);
    _sendDirect(ip, port, msg);
  }

  void _sendGetPeersDirect(String ip, int port) {
    final msg = _encodeGetPeers();
    _sendDirect(ip, port, msg);
  }

  void _sendDirect(String ip, int port, Uint8List data) {
    try {
      final addr = InternetAddress(ip);
      final sent = _socket?.send(data, addr, port) ?? 0;
      if (sent <= 0) {
        debugPrint('DHT: send returned $sent to $ip:$port');
      }
    } catch (e) {
      debugPrint('DHT: send error to $ip:$port: $e');
    }
  }

  // === SOCKET EVENT HANDLER ===

  void _onSocketEvent(RawSocketEvent event) {
    if (event != RawSocketEvent.read) return;

    // Drain all available datagrams
    Datagram? dg;
    while ((dg = _socket?.receive()) != null) {
      _processResponse(dg!);
    }
  }

  void _processResponse(Datagram dg) {
    try {
      final msg = _bdecode(dg.data);
      if (msg is! Map<String, dynamic>) return;

      // Check for error response
      if (msg.containsKey('e')) {
        debugPrint('DHT: Error from ${dg.address.address}: ${msg['e']}');
        return;
      }

      final r = msg['r'];
      if (r is! Map<String, dynamic>) return;

      // Extract compact nodes (26 bytes each: 20-byte ID + 4 IP + 2 port)
      final nodesData = r['nodes'];
      if (nodesData is Uint8List && nodesData.length >= 26) {
        int added = 0;
        for (var i = 0; i + 26 <= nodesData.length; i += 26) {
          final ip = '${nodesData[i + 20]}.${nodesData[i + 21]}.${nodesData[i + 22]}.${nodesData[i + 23]}';
          final p = (nodesData[i + 24] << 8) | nodesData[i + 25];
          if (p > 0 && p < 65536 && ip != '0.0.0.0' && !ip.startsWith('0.')) {
            _routingTable.add(_DhtNode(ip, p));
            added++;
          }
        }
        if (_routingTable.length > 300) {
          _routingTable.removeRange(0, _routingTable.length - 300);
        }
        _dhtNodes = _routingTable.length;
        if (added > 0) {
          debugPrint('DHT: +$added nodes from ${dg.address.address} (total: $_dhtNodes)');
        }
      }

      // Extract peers (list of 6-byte compact peer info)
      final values = r['values'];
      if (values is List) {
        for (final v in values) {
          if (v is Uint8List && v.length >= 6) {
            final ip = '${v[0]}.${v[1]}.${v[2]}.${v[3]}';
            final p = (v[4] << 8) | v[5];
            final key = '$ip:$p';
            if (p > 0 && !_knownPeers.contains(key)) {
              _knownPeers.add(key);
              debugPrint('DHT: Peer found: $key');
              onPeerFound(ip, p);
            }
          }
        }
      }
    } catch (e) {
      debugPrint('DHT: Parse error from ${dg.address.address}: $e');
    }
  }

  // === BENCODE ENCODER ===

  Uint8List _encodeFindNode(Uint8List target) {
    // Manually build: d1:ad2:id20:XXXX6:target20:XXXXe1:q9:find_node1:t4:XXXX1:y1:qe
    final txId = _randomBytes(4);
    final buf = BytesBuilder(copy: false);
    buf.addByte(0x64); // d

    // "a" -> dict
    _addBenStr(buf, 'a');
    buf.addByte(0x64); // d
    _addBenStr(buf, 'id');
    _addBenBytes(buf, _nodeId);
    _addBenStr(buf, 'target');
    _addBenBytes(buf, target);
    buf.addByte(0x65); // e

    // "q" -> "find_node"
    _addBenStr(buf, 'q');
    _addBenStr(buf, 'find_node');

    // "t" -> txId
    _addBenStr(buf, 't');
    _addBenBytes(buf, txId);

    // "y" -> "q"
    _addBenStr(buf, 'y');
    _addBenStr(buf, 'q');

    buf.addByte(0x65); // e (end outer dict)
    return buf.toBytes();
  }

  Uint8List _encodeGetPeers() {
    final txId = _randomBytes(4);
    final buf = BytesBuilder(copy: false);
    buf.addByte(0x64); // d

    // "a" -> dict
    _addBenStr(buf, 'a');
    buf.addByte(0x64); // d
    _addBenStr(buf, 'id');
    _addBenBytes(buf, _nodeId);
    _addBenStr(buf, 'info_hash');
    _addBenBytes(buf, gtalkInfoHash);
    buf.addByte(0x65); // e

    // "q" -> "get_peers"
    _addBenStr(buf, 'q');
    _addBenStr(buf, 'get_peers');

    // "t" -> txId
    _addBenStr(buf, 't');
    _addBenBytes(buf, txId);

    // "y" -> "q"
    _addBenStr(buf, 'y');
    _addBenStr(buf, 'q');

    buf.addByte(0x65); // e
    return buf.toBytes();
  }

  /// Encode a UTF-8 string as bencode string: <len>:<str>
  void _addBenStr(BytesBuilder buf, String s) {
    final bytes = utf8.encode(s);
    buf.add(utf8.encode('${bytes.length}:'));
    buf.add(bytes);
  }

  /// Encode raw bytes as bencode string: <len>:<bytes>
  void _addBenBytes(BytesBuilder buf, Uint8List bytes) {
    buf.add(utf8.encode('${bytes.length}:'));
    buf.add(bytes);
  }

  // === BENCODE DECODER ===

  dynamic _bdecode(Uint8List data) {
    try {
      return _bdecodeAt(data, 0)?.value;
    } catch (_) {
      return null;
    }
  }

  _BDecoded? _bdecodeAt(Uint8List data, int pos) {
    if (pos >= data.length) return null;
    final c = data[pos];

    // Dictionary: d...e
    if (c == 0x64) {
      pos++;
      final map = <String, dynamic>{};
      while (pos < data.length && data[pos] != 0x65) {
        final keyRes = _bdecodeAt(data, pos);
        if (keyRes == null) return null;
        pos = keyRes.end;
        final valRes = _bdecodeAt(data, pos);
        if (valRes == null) return null;
        pos = valRes.end;
        // Keys are always byte strings — decode to String for map access
        final key = (keyRes.value is Uint8List)
            ? utf8.decode(keyRes.value as Uint8List, allowMalformed: true)
            : keyRes.value.toString();
        map[key] = valRes.value;
      }
      if (pos >= data.length) return null;
      return _BDecoded(map, pos + 1); // skip 'e'
    }

    // List: l...e
    if (c == 0x6C) {
      pos++;
      final list = <dynamic>[];
      while (pos < data.length && data[pos] != 0x65) {
        final r = _bdecodeAt(data, pos);
        if (r == null) return null;
        list.add(r.value);
        pos = r.end;
      }
      if (pos >= data.length) return null;
      return _BDecoded(list, pos + 1); // skip 'e'
    }

    // Integer: i<number>e
    if (c == 0x69) {
      pos++;
      int end = pos;
      while (end < data.length && data[end] != 0x65) end++;
      if (end >= data.length) return null;
      final numStr = utf8.decode(data.sublist(pos, end));
      return _BDecoded(int.tryParse(numStr) ?? 0, end + 1);
    }

    // Byte string: <len>:<data>
    if (c >= 0x30 && c <= 0x39) {
      int colonPos = pos;
      while (colonPos < data.length && data[colonPos] != 0x3A) colonPos++;
      if (colonPos >= data.length) return null;
      final lenStr = utf8.decode(data.sublist(pos, colonPos));
      final len = int.tryParse(lenStr);
      if (len == null) return null;
      final start = colonPos + 1;
      final end = start + len;
      if (end > data.length) return null;
      return _BDecoded(Uint8List.fromList(data.sublist(start, end)), end);
    }

    return null;
  }

  // === UTILITIES ===

  Uint8List _randomBytes(int n) {
    final rng = Random.secure();
    return Uint8List.fromList(List.generate(n, (_) => rng.nextInt(256)));
  }

  static Uint8List _sha1(List<int> input) {
    var h0 = 0x67452301;
    var h1 = 0xEFCDAB89;
    var h2 = 0x98BADCFE;
    var h3 = 0x10325476;
    var h4 = 0xC3D2E1F0;

    final data = Uint8List.fromList(input);
    final bitLen = data.length * 8;

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
        w[i] = _rotl(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
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

class _BDecoded {
  final dynamic value;
  final int end;
  _BDecoded(this.value, this.end);
}

class _DhtNode {
  final String ip;
  final int port;
  _DhtNode(this.ip, this.port);
}
