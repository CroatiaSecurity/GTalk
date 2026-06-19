class ChatMessage {
  final String id;
  final String sender;
  final String text;
  final String timestamp;
  final String channel; // "global" or "dm:username"
  final bool isOwn;

  ChatMessage({
    required this.id,
    required this.sender,
    required this.text,
    required this.timestamp,
    required this.channel,
    this.isOwn = false,
  });

  Map<String, dynamic> toJson() => {
    'id': id, 'sender': sender, 'text': text,
    'timestamp': timestamp, 'channel': channel,
  };

  factory ChatMessage.fromJson(Map<String, dynamic> json, String myUsername) =>
    ChatMessage(
      id: json['id'] ?? '',
      sender: json['sender'] ?? 'Unknown',
      text: json['text'] ?? '',
      timestamp: json['timestamp'] ?? '',
      channel: json['channel'] ?? 'global',
      isOwn: json['sender'] == myUsername,
    );
}

class Peer {
  final String username;
  final String address;
  bool isConnected;

  Peer({required this.username, required this.address, this.isConnected = true});
}
