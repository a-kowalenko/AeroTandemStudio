; --- NSIS Installer Skript für Aero Tandem Studio ---

!define APP_NAME "Aero Tandem Studio"
!define APP_VERSION "0.0.1.1337"
!define APP_EXE "Aero Tandem Studio.exe"
!define APP_PUBLISHER "Andreas Kowalenko"
!define APP_WEBSITE "kowalenko.io"

SetCompressor lzma
Name "${APP_NAME}"
OutFile "AeroTandemStudio_Installer_v${APP_VERSION}.exe"
InstallDir "$PROGRAMFILES64\${APP_NAME}"

; Diese Befehle setzen die "Details"-Eigenschaften der EXE-Datei.
VIProductVersion "${APP_VERSION}"
VIAddVersionKey "Publisher" "${APP_PUBLISHER}"
VIAddVersionKey "FileDescription" "${APP_NAME} Installer"
VIAddVersionKey "LegalCopyright" "${APP_PUBLISHER}"
VIAddVersionKey "ProductName" "${APP_NAME}"
VIAddVersionKey "ProductVersion" "${APP_VERSION}"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
VIAddVersionKey "CompanyName" "${APP_PUBLISHER}"
; --- Ende Metadaten ---

!define MUI_ICON "assets\icon.ico"
!define MUI_UNICON "assets\icon.ico"

!include "MUI2.nsh"

; --- Willkommensseite anpassen ---
!define MUI_WELCOMEPAGE_TITLE "Willkommen beim ${APP_NAME} Setup"
!define MUI_WELCOMEPAGE_TEXT "Dieses Setup-Programm installiert ${APP_NAME} auf deinem Computer.$\r$\n$\r$\nDamit die Anwendung ordnungsgemäß funktioniert, werden zusätzlich eine portable Version des VLC Players sowie das Programm FFmpeg installiert. Ohne diese Komponenten funktioniert ${APP_NAME} nicht.$\r$\n$\r$\nKlicke auf 'Weiter', um fortzufahren."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "license.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "German"
!insertmacro MUI_LANGUAGE "English"


; --- Installations-Sektion ---
Section "Aero Tandem Studio (erforderlich)" SecApp
  SetOutPath $INSTDIR

  ; HIER PASSIERT DIE MAGIE (NEU):
  ; 1. Kopiere den gesamten Inhalt des PyInstaller-Ordners
  ; Dies kopiert Aero Tandem Studio.exe und alle Python-DLLs/Abhängigkeiten
  File /r "dist\Aero Tandem Studio\*"

  ; 2. Erstelle die Asset-Ordner-Struktur
  SetOutPath $INSTDIR\assets\ffmpeg
  File /r "assets\ffmpeg\*"

  SetOutPath $INSTDIR\assets\vlc
  File /r "assets\vlc\*"

  ; 3. Erstelle einen leeren Config-Ordner
  SetOutPath $INSTDIR\config
  ; (Optional: Kopieren Sie eine Standard-Konfigurationsdatei hinein)
  ; File "config\default_settings.json"

  ; Setze den Pfad zurück auf das Stammverzeichnis für den Uninstaller
  SetOutPath $INSTDIR

  ; Deinstallations-Informationen
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "Publisher" "${APP_PUBLISHER}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayIcon" "$INSTDIR\${APP_EXE}"

  WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

; --- Sektionen für Verknüpfungen (bleiben gleich) ---
Section "Desktop-Verknüpfung" SecDesktopShortcut
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
SectionEnd

Section "Startmenü-Verknüpfung" SecStartMenu
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\Deinstallieren.lnk" "$INSTDIR\uninstall.exe"
SectionEnd


; --- Deinstallations-Sektion (NEU) ---
Section "Uninstall"
  ; Lösche das gesamte Installationsverzeichnis
  ; RMDir /r löscht rekursiv den gesamten Ordner
  RMDir /r "$INSTDIR"

  ; Verknüpfungen löschen
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Deinstallieren.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"

  ; Registry-Einträge löschen
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
SectionEnd