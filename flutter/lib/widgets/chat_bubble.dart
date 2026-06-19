import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../models/message.dart';
import '../theme/app_theme.dart';

class ChatBubbleWidget extends StatelessWidget {
  final ChatMessage message;
  const ChatBubbleWidget({super.key, required this.message});

  static final _urlRegex = RegExp(r'(https?://[^\s<>"]+)');

  @override
  Widget build(BuildContext context) {
    final isOwn = message.isOwn;
    return Align(
      alignment: isOwn ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: EdgeInsets.only(
          left: isOwn ? 60 : 8, right: isOwn ? 8 : 60,
          top: 3, bottom: 3,
        ),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: isOwn ? AppTheme.bubbleSelf : AppTheme.bubblePeer,
          borderRadius: BorderRadius.circular(14),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            // Sender + time
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(message.sender,
                  style: TextStyle(
                    color: isOwn ? AppTheme.green : AppTheme.accent,
                    fontSize: 11, fontWeight: FontWeight.bold)),
                const SizedBox(width: 8),
                Text(message.timestamp,
                  style: const TextStyle(color: AppTheme.textMuted, fontSize: 10)),
              ],
            ),
            const SizedBox(height: 3),
            // Message with clickable links
            _buildRichText(message.text),
          ],
        ),
      ),
    );
  }

  Widget _buildRichText(String text) {
    final spans = <InlineSpan>[];
    int lastEnd = 0;

    for (final match in _urlRegex.allMatches(text)) {
      if (match.start > lastEnd) {
        spans.add(TextSpan(
          text: text.substring(lastEnd, match.start),
          style: const TextStyle(color: AppTheme.text, fontSize: 13),
        ));
      }
      final url = match.group(0)!;
      spans.add(TextSpan(
        text: url,
        style: const TextStyle(color: AppTheme.accent, fontSize: 13, decoration: TextDecoration.underline),
        recognizer: TapGestureRecognizer()..onTap = () => launchUrl(Uri.parse(url)),
      ));
      lastEnd = match.end;
    }
    if (lastEnd < text.length) {
      spans.add(TextSpan(
        text: text.substring(lastEnd),
        style: const TextStyle(color: AppTheme.text, fontSize: 13),
      ));
    }

    return RichText(text: TextSpan(children: spans));
  }
}
