# Changelog

All notable changes to GTalk will be documented in this file.

## [0.1.0] - 2026-06-19

### Added
- **Single-Instance Enforcement:** Introduced a local named socket-based system check (`QLocalServer`/`QLocalSocket`) that blocks multiple instances from running concurrently. New launch attempts automatically signal and restore the main window of the already running app.
- **Improved System Tray Handling:** Added support for both single-click and double-click actions on the tray icon to reliably restore, normalize, and focus the window on screen.

### Changed
- **Libtorrent 2.0+ Upgrade:** Rewrote session configuration to support modern `libtorrent` (2.0.x) bindings, passing configurations as dictionary properties of `session_params` rather than using the legacy `settings_pack` API.
- **Corrected Initialization Sequence:** Moved swarm engine start after GUI construction to prevent initialization race conditions with PyQt6 UI widgets.
- **CI Dependency Bundling:** Configured the GitHub Actions build workflows to install `libtorrent` on the runners so PyInstaller correctly bundles the DHT library inside compiled binaries for all target OS platforms (Windows, Linux, macOS).
