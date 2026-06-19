# Changelog

All notable changes to GTalk will be documented in this file.

## [0.1.0] - 2026-06-19

### Added
- **Flutter Multiplatform Releases:** Configured GitHub Actions to build and release official single-file packages for the Flutter application across all 5 platforms:
  - Windows: Single-file Setup installer executable (`GTalk-Flutter-Setup.exe`).
  - macOS: Mounted Disk Image (`GTalk-macOS-Flutter.dmg`).
  - Linux: Clean compressed tarball (`GTalk-Linux-Flutter.tar.gz`).
  - Android: Installable `.apk` file (`app-release.apk`).
  - iOS: Standard `.ipa` archive bundle (`GTalk-iOS-Flutter.ipa`).
- **Python App Single-Instance & Tray Fixes:** Implemented a single-instance check using `QLocalServer`/`QLocalSocket` and enhanced system tray single/double click window restoration for developers running `gtalk.py` from source.
- **Flutter Socket Binding Safety:** Added `try-catch` safety to the Flutter TCP listener socket bind. If port 31337 is busy, the app falls back gracefully to outbound-only mode rather than crashing on startup.

### Changed
- **Libtorrent 2.0+ Upgrade (Python):** Updated `gtalk.py` to support `libtorrent` 2.0+ using dictionary-based `session_params` configuration instead of the deprecated `settings_pack` API.
- **Corrected Python Initialization Order:** Moved swarm engine start after GUI creation to resolve a widget initialization race condition.
- **Simplified Workflow:** Removed the Python PyInstaller build workflow, prioritizing the Flutter app as the official build and release technology.
