import 'package:flutter/material.dart';

/// Chrome-dark theme matching GBrowser/Ceprkac
class AppTheme {
  static const background = Color(0xFF202124);
  static const surface = Color(0xFF292A2D);
  static const surfaceAlt = Color(0xFF35363A);
  static const sidebar = Color(0xFF1C1C1F);
  static const input = Color(0xFF3C4043);
  static const border = Color(0xFF3C4043);
  static const text = Color(0xFFFFFFFF);
  static const textDim = Color(0xFF80868E);
  static const textMuted = Color(0xFF5F6368);
  static const accent = Color(0xFF8AB4F8);
  static const green = Color(0xFF81C995);
  static const red = Color(0xFFF28B82);
  static const bubbleSelf = Color(0xFF1A3A5C);
  static const bubblePeer = Color(0xFF35363A);

  static ThemeData get darkTheme => ThemeData(
    brightness: Brightness.dark,
    scaffoldBackgroundColor: background,
    primaryColor: accent,
    colorScheme: const ColorScheme.dark(
      primary: accent,
      surface: surface,
      onSurface: text,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: sidebar,
      foregroundColor: text,
      elevation: 0,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: input,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(24),
        borderSide: const BorderSide(color: border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(24),
        borderSide: const BorderSide(color: border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(24),
        borderSide: const BorderSide(color: accent),
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      hintStyle: const TextStyle(color: textMuted),
    ),
    listTileTheme: const ListTileThemeData(
      textColor: text,
      iconColor: textDim,
    ),
    fontFamily: 'Segoe UI',
  );
}
