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
