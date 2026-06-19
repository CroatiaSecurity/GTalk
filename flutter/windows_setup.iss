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
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "build\windows\x64\runner\Release\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\GTalk Flutter"; Filename: "{app}\gtalk.exe"
Name: "{autodesktop}\GTalk Flutter"; Filename: "{app}\gtalk.exe"

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""GTalk Flutter"" dir=in action=allow program=""{app}\gtalk.exe"" enable=yes"; Flags: runhidden
Filename: "{app}\gtalk.exe"; Description: "{cm:LaunchProgram,GTalk Flutter}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""GTalk Flutter"""; Flags: runhidden
