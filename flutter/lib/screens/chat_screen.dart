import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';
import '../models/message.dart';
import '../services/peer_service.dart';
import '../theme/app_theme.dart';
import '../widgets/chat_bubble.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _msgController = TextEditingController();
  final _scrollController = ScrollController();
  final List<ChatMessage> _messages = [];
  String _currentChannel = 'global';

  @override
  void initState() {
    super.initState();
    final peerService = context.read<PeerService>();
    peerService.messages.listen((msg) {
      if (msg.channel == _currentChannel) {
        setState(() => _messages.add(msg));
        _scrollToBottom();
      }
    });
  }

  void _scrollToBottom() {
    Future.delayed(const Duration(milliseconds: 50), () {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _send() {
    final text = _msgController.text.trim();
    if (text.isEmpty) return;
    _msgController.clear();

    final peerService = context.read<PeerService>();
    final msg = ChatMessage(
      id: DateTime.now().millisecondsSinceEpoch.toString(),
      sender: peerService.username,
      text: text,
      timestamp: '${DateTime.now().hour.toString().padLeft(2, '0')}:${DateTime.now().minute.toString().padLeft(2, '0')}',
      channel: _currentChannel,
      isOwn: true,
    );

    setState(() => _messages.add(msg));
    _scrollToBottom();

    if (_currentChannel == 'global') {
      peerService.sendToGlobal(text);
    } else {
      peerService.sendDm(_currentChannel.replaceFirst('dm:', ''), text);
    }
  }

  void _switchChannel(String channel) {
    setState(() {
      _currentChannel = channel;
      _messages.clear(); // In production, load from local DB
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Row(
        children: [
          // === LEFT PANEL: Users ===
          _buildSidebar(),
          // === CHAT ===
          Expanded(child: _buildChat()),
        ],
      ),
    );
  }

  Widget _buildSidebar() {
    return Consumer<PeerService>(
      builder: (context, peerService, _) {
        return Container(
          width: 220,
          color: AppTheme.sidebar,
          child: Column(
            children: [
              // Header
              Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  children: [
                    const Text('💬 ', style: TextStyle(fontSize: 18)),
                    Text('GTalk', style: TextStyle(
                      color: AppTheme.accent, fontSize: 16, fontWeight: FontWeight.bold)),
                  ],
                ),
              ),
              // DHT status
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Text(
                  'DHT: ${peerService.dhtNodes} nodes',
                  style: const TextStyle(color: AppTheme.textMuted, fontSize: 10),
                ),
              ),
              const SizedBox(height: 12),
              // Global room button
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                child: ListTile(
                  dense: true,
                  leading: const Text('🌐', style: TextStyle(fontSize: 16)),
                  title: const Text('Global Room', style: TextStyle(fontSize: 13)),
                  selected: _currentChannel == 'global',
                  selectedTileColor: AppTheme.surfaceAlt,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                  onTap: () => _switchChannel('global'),
                ),
              ),
              const SizedBox(height: 8),
              // Online label
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Row(
                  children: [
                    Text('ONLINE — ${peerService.onlineCount}',
                      style: const TextStyle(color: AppTheme.textMuted, fontSize: 10, fontWeight: FontWeight.bold)),
                  ],
                ),
              ),
              const SizedBox(height: 4),
              // User list
              Expanded(
                child: ListView.builder(
                  itemCount: peerService.peers.length,
                  itemBuilder: (context, i) {
                    final peer = peerService.peers[i];
                    return Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 1),
                      child: ListTile(
                        dense: true,
                        leading: Container(
                          width: 8, height: 8,
                          decoration: const BoxDecoration(
                            color: AppTheme.green, shape: BoxShape.circle),
                        ),
                        title: Text(peer.username, style: const TextStyle(fontSize: 13)),
                        selected: _currentChannel == 'dm:${peer.username}',
                        selectedTileColor: AppTheme.surfaceAlt,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                        onTap: () => _switchChannel('dm:${peer.username}'),
                      ),
                    );
                  },
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildChat() {
    return Column(
      children: [
        // Channel header
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: const BoxDecoration(
            color: AppTheme.sidebar,
            border: Border(bottom: BorderSide(color: AppTheme.border)),
          ),
          child: Row(
            children: [
              Text(
                _currentChannel == 'global' ? '🌐 Global Room' : '💬 ${_currentChannel.replaceFirst("dm:", "")}',
                style: const TextStyle(color: AppTheme.text, fontSize: 15, fontWeight: FontWeight.bold),
              ),
            ],
          ),
        ),
        // Messages
        Expanded(
          child: ListView.builder(
            controller: _scrollController,
            padding: const EdgeInsets.all(12),
            itemCount: _messages.length,
            itemBuilder: (context, i) => ChatBubbleWidget(message: _messages[i]),
          ),
        ),
        // Input bar
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: const BoxDecoration(
            color: AppTheme.surface,
            border: Border(top: BorderSide(color: AppTheme.border)),
          ),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _msgController,
                  style: const TextStyle(color: AppTheme.text),
                  decoration: const InputDecoration(
                    hintText: 'Type a message...',
                    isDense: true,
                  ),
                  onSubmitted: (_) => _send(),
                ),
              ),
              const SizedBox(width: 8),
              ElevatedButton(
                onPressed: _send,
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppTheme.accent,
                  foregroundColor: AppTheme.background,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                ),
                child: const Text('Send', style: TextStyle(fontWeight: FontWeight.bold)),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
