import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'services/peer_service.dart';
import 'screens/chat_screen.dart';
import 'theme/app_theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final prefs = await SharedPreferences.getInstance();
  final username = prefs.getString('username') ?? 'User_${DateTime.now().millisecondsSinceEpoch % 10000}';

  final peerService = PeerService(username: username);
  await peerService.start();

  runApp(GTalkApp(peerService: peerService));
}

class GTalkApp extends StatelessWidget {
  final PeerService peerService;
  const GTalkApp({super.key, required this.peerService});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider.value(
      value: peerService,
      child: MaterialApp(
        title: 'GTalk',
        theme: AppTheme.darkTheme,
        debugShowCheckedModeBanner: false,
        home: const ChatScreen(),
      ),
    );
  }
}
