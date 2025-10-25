; --- NSIS Installer Skript für Aero Tandem Studio ---
; WICHTIG: Dieses Skript muss als "UTF-8 mit BOM" gespeichert werden.
Unicode true

!define APP_NAME "Aero Tandem Studio"
!define APP_VERSION "0.0.1.1337"
!define APP_EXE "${APP_NAME}.exe"
!define APP_PUBLISHER "Andreas Kowalenko"
!define APP_WEBSITE "kowalenko.io"
!define VLC_SETUP_EXE "dependency_installer\vlc-3.0.21-win64.exe"
!define FFMPEG_SETUP_ZIP "ffmpeg-8.0-essentials_build.zip"
!define FFMPEG_SETUP_ZIP_PATH "dependency_installer\${FFMPEG_SETUP_ZIP}"

; Name des Installers selbst
Name "${APP_NAME}"
OutFile "AeroTandemStudio_Installer_v${APP_VERSION}.exe"
SetCompressor lzma
RequestExecutionLevel admin

; Standard-Installationspfad
InstallDir "$PROGRAMFILES64\${APP_NAME}"

; --- Metadaten ---
VIProductVersion "${APP_VERSION}"
VIAddVersionKey "Publisher" "${APP_PUBLISHER}"
VIAddVersionKey "FileDescription" "${APP_NAME} Installer"
VIAddVersionKey "LegalCopyright" "${APP_PUBLISHER}"
VIAddVersionKey "ProductName" "${APP_NAME}"
VIAddVersionKey "ProductVersion" "${APP_VERSION}"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
VIAddVersionKey "CompanyName" "${APP_PUBLISHER}"

; --- MUI Seiten (User Interface) ---
!include "MUI2.nsh"

!define MUI_ICON "assets\icon.ico"
!define MUI_UNICON "assets\icon.ico"

; --- Willkommens-Seite ---
!define MUI_WELCOMEPAGE_TITLE "Willkommen beim ${APP_NAME} Setup"
!define MUI_WELCOMEPAGE_TEXT "Dieses Setup-Programm installiert ${APP_NAME} auf deinem Computer.$\r$\n$\r$\nDamit die Anwendung ordnungsgemäß funktioniert, wird zusätzlich der 'VLC Player' sowie 'FFmpeg' installiert. Ohne diese Komponenten funktioniert ${APP_NAME} nicht.$\r$\n$\r$\nKlicke auf 'Weiter', um fortzufahren."
!insertmacro MUI_PAGE_WELCOME

; --- Lizenz-Seite ---
!insertmacro MUI_PAGE_LICENSE "license.txt"

; --- Komponenten-Seite ---
!insertmacro MUI_PAGE_COMPONENTS

; --- Verzeichnis-Auswahl-Seite ---
!insertmacro MUI_PAGE_DIRECTORY

; --- Installations-Seite ---
!insertmacro MUI_PAGE_INSTFILES

; --- Abschluss-Seite (Mit "App starten"-Checkbox) ---
!define MUI_FINISHPAGE_TITLE "Installation von ${APP_NAME} abgeschlossen"
!define MUI_FINISHPAGE_TEXT "Das Setup hat ${APP_NAME} erfolgreich auf Ihrem Computer installiert."
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "${APP_NAME} jetzt starten"
!insertmacro MUI_PAGE_FINISH

; --- Deinstaller-Seiten ---
!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

; --- Sprache ---
!insertmacro MUI_LANGUAGE "German"

; --- Sprachstrings für Beschreibungen ---
LangString DESC_SectionVLC ${LANG_GERMAN} "Installiert den VLC Media Player, der für die Videowiedergabe benötigt wird."
LangString DESC_SectionFFMPEG ${LANG_GERMAN} "Installiert FFmpeg für Video- und Audioverarbeitung."
LangString DESC_SectionApp ${LANG_GERMAN} "Installiert die Hauptanwendung ${APP_NAME}."

; ===================================================================
; ======================== INSTALLATIONS-SEKTIONEN ==================
; ===================================================================

; --- VLC Media Player ---
Section "VLC Media Player (Erforderlich)" SectionVLC
    SectionIn RO
    SetDetailsPrint both
    DetailPrint "Überprüfe VLC-Installation..."

    ; --- Registry prüfen (64-bit + 32-bit) ---
    SetRegView 64
    ReadRegStr $0 HKLM "SOFTWARE\VideoLAN\VLC" "InstallDir"
    ${If} $0 == ""
        SetRegView 32
        ReadRegStr $0 HKLM "SOFTWARE\VideoLAN\VLC" "InstallDir"
    ${EndIf}
    SetRegView lastused

    ${If} $0 != ""
        IfFileExists "$0\vlc.exe" VLC_Found
    ${EndIf}

    ; --- VLC nicht gefunden, installiere es ---
    DetailPrint "VLC wird installiert..."
    SetOutPath $TEMP
    File /oname=vlc_installer.exe "${VLC_SETUP_EXE}"

    ExecWait '"$TEMP\vlc_installer.exe" /S /L=1031 /NCRC' $1

    ${If} $1 != 0
        MessageBox MB_ICONEXCLAMATION "VLC-Installation fehlgeschlagen. Fehlercode: $1"
    ${Else}
        DetailPrint "VLC wurde erfolgreich installiert."
    ${EndIf}

    Delete "$TEMP\vlc_installer.exe"
    Goto VLC_End

VLC_Found:
    DetailPrint "VLC ist bereits installiert."

VLC_End:
    SetDetailsPrint lastused
SectionEnd



; --- FFmpeg (Pflichtinstallation) ---
Section "FFmpeg (Erforderlich)" SectionFFmpeg
    ; Admin-Rechte prüfen
    UserInfo::GetAccountType
    pop $0
    StrCmp $0 "Admin" +3
        MessageBox MB_ICONSTOP "Administrator-Rechte erforderlich!"
        Abort

    SectionIn RO
    SetDetailsPrint both
    DetailPrint "Installiere FFmpeg..."

    ; --- 1. Prüfen, ob die ZIP existiert (KORRIGIERTE LOGIK) ---
    StrCpy $0 "$EXEDIR\${FFMPEG_SETUP_ZIP_PATH}"

    DetailPrint "Prüfe auf Existenz von: $0"

    ; Wir prüfen NUR noch diesen absoluten Pfad.
    IfFileExists "$0" zip_exists

    ; Wenn wir hier landen, wurde die Datei nicht gefunden.
    DetailPrint "Fehler: ZIP-Datei nicht am erwarteten Ort gefunden."
    MessageBox MB_ICONSTOP "FFmpeg-ZIP-Datei nicht gefunden.$\r$\n$\r$\nDie Datei wurde nicht am folgenden Ort gefunden:$\r$\n$0$\r$\n$\r$\nBitte stellen Sie sicher, dass sich der Ordner 'dependency_installer' im selben Verzeichnis wie der Installer befindet."
    Abort

    zip_exists:
        DetailPrint "Extrahiere mitgelieferte FFmpeg ZIP (Quelle: $0)..."

        ; --- 2. Zielordner vorbereiten ---
        SetOutPath "$INSTDIR\ffmpeg"
        RMDir /r "$INSTDIR\ffmpeg_temp"

        ; $0 ist jetzt garantiert ein absoluter Pfad, CopyFiles wird funktionieren.
        CopyFiles "$0" "$INSTDIR\ffmpeg.zip"

        IfFileExists "$INSTDIR\ffmpeg.zip" 0 copy_zip_failed

        Goto extract_zip

    copy_zip_failed:
        DetailPrint "FEHLER: Konnte die ZIP-Datei nicht nach $INSTDIR\ffmpeg.zip kopieren."
        MessageBox MB_ICONSTOP "Konnte die FFmpeg-ZIP nicht in das Installationsverzeichnis kopieren.$\r$\n(Mögliche Ursachen: Antivirus blockiert Zugriff).$\r$\n$\r$\nQuelle: $0$\r$\nZiel: $INSTDIR\ffmpeg.zip"
        Abort

    extract_zip:
        ; --- 3. ZIP Extrahieren (mit Fehlerabfang) ---
        DetailPrint "Entpacke $INSTDIR\ffmpeg.zip nach $INSTDIR\ffmpeg_temp..."

        nsExec::ExecToStack "powershell -NoProfile -ExecutionPolicy Bypass -Command $\"$ErrorActionPreference = 'Stop'; & {Add-Type -A System.IO.Compression.FileSystem; [IO.Compression.ZipFile]::ExtractToDirectory('$INSTDIR\ffmpeg.zip', '$INSTDIR\ffmpeg_temp')}$\""

        Pop $1 ; $1 = Rückgabecode
        Pop $2 ; $2 = PowerShell-Output/Fehlermeldung

        StrCmp $1 "0" extract_ok extract_fail

    extract_fail:
        DetailPrint "Fehler beim Extrahieren der ZIP. (Code: $1)"
        MessageBox MB_ICONSTOP "FFmpeg-ZIP konnte nicht extrahiert werden.$\r$\n(Mögl. Ursache: Virenscanner oder fehlende Admin-Rechte).$\r$\n$\r$\nFehlerdetails:$\r$\n$2"
        ; Aufräumen
        Delete "$INSTDIR\ffmpeg.zip"
        RMDir /r "$INSTDIR\ffmpeg_temp"
        RMDir /r "$INSTDIR\ffmpeg"
        Abort

    extract_ok:
        DetailPrint "ZIP erfolgreich extrahiert."

        ; --- 4. PRÜFUNG: Wurde der Ordner wirklich erstellt? ---
        IfFileExists "$INSTDIR\ffmpeg_temp" 0 extract_empty

        DetailPrint "Temporärer Ordner $INSTDIR\ffmpeg_temp wurde gefunden."
        Goto copy_files

    extract_empty:
        DetailPrint "FEHLER: Extraktion meldete Erfolg (0), aber der Zielordner '$INSTDIR\ffmpeg_temp' wurde nicht erstellt."
        MessageBox MB_ICONSTOP "FFmpeg-ZIP konnte nicht installiert werden.$\r$\n(Unbekannter Fehler: Virenscanner oder Rechteproblem).$\r$\nDie ZIP-Datei selbst scheint NICHT leer zu sein."
        ; Aufräumen
        Delete "$INSTDIR\ffmpeg.zip"
        RMDir /r "$INSTDIR\ffmpeg"
        Abort

    copy_files:
    ; --- 5. Benötigte Dateien kopieren (KORRIGIERT) ---
    DetailPrint "Kopiere FFmpeg-Binärdateien..."

    ; Direkt aus ffmpeg_temp\bin kopieren, falls vorhanden
    IfFileExists "$INSTDIR\ffmpeg_temp\bin\*.*" copy_from_bin

    ; Falls nicht, prüfen ob es ein Root-Verzeichnis gibt (für andere ZIP-Strukturen)
    IfFileExists "$INSTDIR\ffmpeg_temp\*\bin\*.*" copy_from_subdir

    ; Keine passende Struktur gefunden
    DetailPrint "FEHLER: Keine gültige FFmpeg-Struktur in der ZIP gefunden."
    Goto copy_fail

    copy_from_bin:
        DetailPrint "Kopiere aus direkter bin-Struktur..."
        CopyFiles "$INSTDIR\ffmpeg_temp\bin\*.*" "$INSTDIR\ffmpeg\"
        Goto verify_copy

    copy_from_subdir:
        DetailPrint "Kopiere aus Unterverzeichnis-Struktur..."
        ; PowerShell-Logik für den Fall mit Root-Verzeichnis
        nsExec::ExecToStack "powershell -NoProfile -ExecutionPolicy Bypass -Command $\"$ErrorActionPreference = 'Stop'; $$RootDir = Get-ChildItem '$INSTDIR\ffmpeg_temp' -Directory | Select-Object -First 1; if (-not $$RootDir) { Write-Error 'Kein Stammverzeichnis gefunden'; exit 1 }; $$SourceBinDir = Join-Path -Path $$RootDir.FullName -ChildPath 'bin'; if (Test-Path $$SourceBinDir) { Copy-Item -Path ($$SourceBinDir + '\*') -Destination '$INSTDIR\ffmpeg' -Recurse -Force } else { Write-Error ('bin-Ordner nicht gefunden: ' + $$SourceBinDir); exit 1 }$\""
        Pop $1
        Pop $2
        StrCmp $1 "0" verify_copy copy_fail

    verify_copy:
        ; Prüfen ob Dateien kopiert wurden
        IfFileExists "$INSTDIR\ffmpeg\ffmpeg.exe" copy_ok
        DetailPrint "FEHLER: ffmpeg.exe nach Kopiervorgang nicht gefunden."
        Goto copy_fail

    copy_fail:
        DetailPrint "Fehler beim Kopieren der FFmpeg-Dateien. (Code: $1)"
        MessageBox MB_ICONSTOP "FFmpeg-Dateien konnten nicht kopiert werden.$\r$\nUnerwartete ZIP-Struktur.$\r$\nFehlerdetails:$\r$\n$2"
        ; Aufräumen
        Delete "$INSTDIR\ffmpeg.zip"
        RMDir /r "$INSTDIR\ffmpeg_temp"
        RMDir /r "$INSTDIR\ffmpeg"
        Abort

    copy_ok:
        DetailPrint "FFmpeg-Dateien erfolgreich kopiert."


        ; --- 6. Aufräumen ---
        Delete "$INSTDIR\ffmpeg.zip"
        RMDir /r "$INSTDIR\ffmpeg_temp"

        ; --- 7. Finale Prüfung und Registrierung ---
        IfFileExists "$INSTDIR\ffmpeg\ffmpeg.exe" ffmpeg_ok no_bin

    no_bin:
        DetailPrint "FEHLER: ffmpeg.exe wurde nach dem Kopieren nicht am Zielort gefunden."
        MessageBox MB_ICONSTOP "FFmpeg konnte nicht korrekt installiert werden (unbekannter Kopierfehler)."
        RMDir /r "$INSTDIR\ffmpeg"
        Abort

    ffmpeg_ok:
        DetailPrint "FFmpeg erfolgreich installiert."
        WriteRegStr HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "FFMPEG_PATH" "$INSTDIR\ffmpeg"

    SetDetailsPrint lastused
SectionEnd




; --- Hauptanwendung ---
Section "${APP_NAME} (Erforderlich)" SectionApp
    SectionIn RO
    SetDetailsPrint both
    DetailPrint "Installiere ${APP_NAME}..."

    SetOutPath "$INSTDIR"
    File /r "dist\${APP_NAME}\*.*"

    ; Registry für App Paths
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\App Paths\${APP_EXE}" "" "$INSTDIR\${APP_EXE}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\App Paths\${APP_EXE}" "Path" "$INSTDIR"

    ; Verknüpfungen
    CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
    CreateShortcut "$SMPROGRAMS\${APP_NAME}\Deinstallieren.lnk" "$INSTDIR\uninstall.exe"

    DetailPrint "${APP_NAME} wurde installiert."
    SetDetailsPrint lastused
SectionEnd

; --- Post-Installations Sektion ---
Section -Post
    SetDetailsPrint both
    DetailPrint "Erstelle Deinstallationsprogramm..."

    WriteUninstaller "$INSTDIR\uninstall.exe"

    ; Registry für Add/Remove Programs
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayName" "${APP_NAME}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "UninstallString" '"$INSTDIR\uninstall.exe"'
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "Publisher" "${APP_PUBLISHER}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "URLInfoAbout" "${APP_WEBSITE}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "InstallLocation" "$INSTDIR"
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "NoRepair" 1

    DetailPrint "Installation abgeschlossen."
    SetDetailsPrint lastused
SectionEnd

; --- Komponentenbeschreibungen ---
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SectionVLC} $(DESC_SectionVLC)
  !insertmacro MUI_DESCRIPTION_TEXT ${SectionFFMPEG} $(DESC_SectionFFMPEG)
  !insertmacro MUI_DESCRIPTION_TEXT ${SectionApp} $(DESC_SectionApp)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ===================================================================
; ============================ UNINSTALLER ===========================
; ===================================================================

Section "Uninstall"
    SetDetailsPrint both
    DetailPrint "Beende ${APP_NAME}..."

    nsExec::ExecToStack 'taskkill /F /IM "${APP_EXE}"'
    Sleep 2000

    DetailPrint "Entferne Dateien..."
    RMDir /r "$INSTDIR"

    DetailPrint "Entferne Verknüpfungen..."
    Delete "$DESKTOP\${APP_NAME}.lnk"
    RMDir /r "$SMPROGRAMS\${APP_NAME}"

    DetailPrint "Bereinige Registry..."
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\App Paths\${APP_EXE}"

    DetailPrint "Deinstallation abgeschlossen."
    SetDetailsPrint lastused
SectionEnd

; ===================================================================
; ====================== INITIALISIERUNGS-FUNKTIONEN =================
; ===================================================================

Function .onInstSuccess
    IfFileExists "$INSTDIR\${APP_EXE}" installed missing
    installed:
        Return
    missing:
        MessageBox MB_ICONEXCLAMATION "Warnung: Die Hauptanwendung wurde möglicherweise nicht korrekt installiert."
FunctionEnd

Function .onInit
    ; Prüfe auf bereits laufende Instanzen der App (robust, sprachunabhängig)
    ; wir verwenden cmd /C mit findstr: wenn der Prozess gefunden wird, gibt findstr eine Zeile aus
    nsExec::ExecToStack 'cmd /C tasklist /FI "IMAGENAME eq ${APP_EXE}" | findstr /I /C:"${APP_EXE}"'
    Pop $0
    Pop $1
    ; $1 enthält die Ausgabezeile, falls gefunden; leer wenn nicht
    StrCmp $1 "" continue_install found_running

    found_running:
        MessageBox MB_YESNO|MB_ICONEXCLAMATION \
            "${APP_NAME} scheint bereits zu laufen.$\r$\nBitte beenden Sie die Anwendung vor der Installation.$\r$\n$\r$\nJetzt beenden und fortfahren?" \
            /SD IDYES IDYES kill_app IDNO cancel_install

        kill_app:
            nsExec::Exec 'taskkill /F /IM "${APP_EXE}"'
            Sleep 2000
            Goto continue_install

        cancel_install:
            Abort

    continue_install:
FunctionEnd
