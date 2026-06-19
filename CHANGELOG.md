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
- **Flutter Socket Binding Safety:** Added `try-catch` safety to the Flutter TCP listener socket bind. If port 31337 is busy, the app falls back gracefully to outbound-only mode rather than crashing on startup.

### Changed
- **Complete Python Codebase Deprecation:** Removed the legacy Python desktop app script (`gtalk.py`), dependencies (`requirements.txt`), build script (`build.bat`), and GitHub Actions workflow configuration to clean up the repository and establish Flutter as the sole official app technology.
