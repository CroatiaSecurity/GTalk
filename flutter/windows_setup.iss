[Setup]
AppName=GTalk Flutter
AppVersion=0.1.0
DefaultDirName={autopf}\GTalk Flutter
DefaultGroupName=GTalk Flutter
UninstallDisplayIcon={app}\gtalk.exe
Compression=lzma2
SolidCompression=yes
OutputDir=build
OutputBaseFilename=GTalk-Flutter-Setup
SetupIconFile=assets\GTalk.ico

[Files]
Source: "build\windows\x64\runner\Release\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\GTalk Flutter"; Filename: "{app}\gtalk.exe"
Name: "{autodesktop}\GTalk Flutter"; Filename: "{app}\gtalk.exe"

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""GTalk Flutter UDP"" dir=in action=allow protocol=UDP localport=32337"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""GTalk Flutter TCP"" dir=in action=allow protocol=TCP localport=31337"; Flags: runhidden
Filename: "{app}\gtalk.exe"; Description: "{cm:LaunchProgram,GTalk Flutter}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""GTalk Flutter UDP"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""GTalk Flutter TCP"""; Flags: runhidden
