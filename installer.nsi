; --- NSIS Installer Skript für Aero Tandem Studio ---
; WICHTIG: Dieses Skript muss als "UTF-8 mit BOM" gespeichert werden.
Unicode true

!define APP_NAME "Aero Tandem Studio"
!define APP_VERSION "0.0.2.1337"
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
    SectionIn RO
    SetDetailsPrint both
    DetailPrint "Installiere FFmpeg..."

    ; --- Zielordner im Benutzerprofil ---
    StrCpy $1 "$LOCALAPPDATA\ffmpeg"
    DetailPrint "Installiere FFmpeg nach: $1"

    ; --- 1. ZIP-Datei aus Installer-Ressourcen extrahieren ---
    DetailPrint "Extrahiere FFmpeg aus Installer-Ressourcen..."

    ; Temporären Ordner für die Extraktion erstellen
    InitPluginsDir
    StrCpy $2 "$PLUGINSDIR\ffmpeg_temp"

    ; Sicherstellen, dass der temporäre Ordner leer ist
    RMDir /r "$2"
    CreateDirectory "$2"

    ; ZIP-Datei aus Ressourcen in temporären Ordner schreiben
    SetOutPath "$2"
    File "/oname=ffmpeg.zip" "${FFMPEG_SETUP_ZIP_PATH}"

    IfFileExists "$2\ffmpeg.zip" zip_extracted zip_extract_failed

    zip_extract_failed:
        DetailPrint "FEHLER: Konnte FFmpeg-ZIP nicht aus Installer-Ressourcen extrahieren."
        MessageBox MB_ICONSTOP "FFmpeg-ZIP konnte nicht aus Installer-Ressourcen extrahiert werden.$\r$\nMögliche Ursache: Beschädigter Installer."
        Abort

    zip_extracted:
        DetailPrint "FFmpeg-ZIP erfolgreich extrahiert."

        ; --- 2. Zielordner vorbereiten ---
        SetOutPath "$1\bin"
        RMDir /r "$1\temp"
        CreateDirectory "$1\temp"

        ; ZIP in Installationsverzeichnis kopieren
        CopyFiles "$2\ffmpeg.zip" "$1\temp.zip"

        ; Temporäre Dateien bereinigen
        Delete "$2\ffmpeg.zip"
        RMDir /r "$2"

        IfFileExists "$1\temp.zip" 0 copy_zip_failed
        Goto extract_zip

    copy_zip_failed:
        DetailPrint "FEHLER: Konnte die ZIP-Datei nicht nach $1\temp.zip kopieren."
        MessageBox MB_ICONSTOP "Konnte die FFmpeg-ZIP nicht in das Benutzerverzeichnis kopieren.$\r$\n(Mögliche Ursachen: Fehlende Schreibrechte)."
        Abort

    extract_zip:
        ; --- 3. ZIP Extrahieren (mit Fehlerabfang) ---
        DetailPrint "Entpacke $1\temp.zip nach $1\temp..."

        ; PowerShell-Befehl mit einfacherer Syntax
        nsExec::ExecToStack 'powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::ExtractToDirectory(\"$1\\temp.zip\", \"$1\\temp\")"'

        Pop $2 ; $2 = Rückgabecode
        Pop $3 ; $3 = PowerShell-Output/Fehlermeldung

        StrCmp $2 "0" extract_ok extract_fail

    extract_fail:
        DetailPrint "Fehler beim Extrahieren der ZIP. (Code: $2)"
        MessageBox MB_ICONSTOP "FFmpeg-ZIP konnte nicht extrahiert werden.$\r$\n(Mögl. Ursache: Fehlende Schreibrechte).$\r$\n$\r$\nFehlerdetails:$\r$\n$3"
        ; Aufräumen
        Delete "$1\temp.zip"
        RMDir /r "$1\temp"
        RMDir /r "$1"
        Abort

    extract_ok:
        DetailPrint "ZIP erfolgreich extrahiert."

        ; --- 4. PRÜFUNG: Wurde der Ordner wirklich erstellt? ---
        IfFileExists "$1\temp" 0 extract_empty

        DetailPrint "Temporärer Ordner $1\temp wurde gefunden."
        Goto copy_files

    extract_empty:
        DetailPrint "FEHLER: Extraktion meldete Erfolg (0), aber der Zielordner '$1\temp' wurde nicht erstellt."
        MessageBox MB_ICONSTOP "FFmpeg-ZIP konnte nicht installiert werden.$\r$\n(Unbekannter Fehler: Fehlende Schreibrechte)."
        ; Aufräumen
        Delete "$1\temp.zip"
        RMDir /r "$1"
        Abort

    copy_files:
    ; --- 5. Benötigte Dateien kopieren ---
    DetailPrint "Kopiere FFmpeg-Binärdateien nach $1\bin..."

    ; Direkt aus temp\bin kopieren, falls vorhanden
    IfFileExists "$1\temp\bin\*.*" copy_from_bin

    ; Falls nicht, prüfen ob es ein Root-Verzeichnis gibt (für andere ZIP-Strukturen)
    IfFileExists "$1\temp\*\bin\*.*" copy_from_subdir

    ; Keine passende Struktur gefunden
    DetailPrint "FEHLER: Keine gültige FFmpeg-Struktur in der ZIP gefunden."
    Goto copy_fail

    copy_from_bin:
        DetailPrint "Kopiere aus direkter bin-Struktur..."
        CopyFiles "$1\temp\bin\*.*" "$1\bin\"
        Goto verify_copy

    copy_from_subdir:
        DetailPrint "Kopiere aus Unterverzeichnis-Struktur..."
        ; PowerShell-Befehl mit korrekter Syntax
        nsExec::ExecToStack 'powershell -NoProfile -ExecutionPolicy Bypass -Command "$$RootDir = Get-ChildItem ''$1\temp'' -Directory | Select-Object -First 1; if ($$RootDir) { $$SourceBinDir = Join-Path -Path $$RootDir.FullName -ChildPath ''bin''; if (Test-Path $$SourceBinDir) { Copy-Item -Path (Join-Path $$SourceBinDir ''*'') -Destination ''$1\bin'' -Recurse -Force } else { Write-Error ''bin-Ordner nicht gefunden''; exit 1 } } else { Write-Error ''Kein Stammverzeichnis gefunden''; exit 1 }"'

        Pop $2
        Pop $3
        StrCmp $2 "0" verify_copy copy_fail

    verify_copy:
        ; Prüfen ob Dateien kopiert wurden
        IfFileExists "$1\bin\ffmpeg.exe" copy_ok
        DetailPrint "FEHLER: ffmpeg.exe nach Kopiervorgang nicht gefunden."
        Goto copy_fail

    copy_fail:
        DetailPrint "Fehler beim Kopieren der FFmpeg-Dateien. (Code: $2)"
        MessageBox MB_ICONSTOP "FFmpeg-Dateien konnten nicht kopiert werden.$\r$\nUnerwartete ZIP-Struktur.$\r$\nFehlerdetails:$\r$\n$3"
        ; Aufräumen
        Delete "$1\temp.zip"
        RMDir /r "$1\temp"
        RMDir /r "$1"
        Abort

    copy_ok:
        DetailPrint "FFmpeg-Dateien erfolgreich kopiert."

        ; --- 6. Aufräumen ---
        Delete "$1\temp.zip"
        RMDir /r "$1\temp"

        ; --- 7. Finale Prüfung und PATH-Registrierung ---
        IfFileExists "$1\bin\ffmpeg.exe" ffmpeg_ok no_bin

    no_bin:
        DetailPrint "FEHLER: ffmpeg.exe wurde nach dem Kopieren nicht am Zielort gefunden."
        MessageBox MB_ICONSTOP "FFmpeg konnte nicht korrekt installiert werden (unbekannter Kopierfehler)."
        RMDir /r "$1"
        Abort

    ffmpeg_ok:
        DetailPrint "FFmpeg erfolgreich installiert in Benutzerverzeichnis."

        ; --- PATH-Registrierung im Benutzerkontext ---
        DetailPrint "Füge FFmpeg zum Benutzer-PATH hinzu..."

        ; Aktuellen Benutzer-PATH aus Registry lesen
        ReadRegStr $4 HKCU "Environment" "Path"

        ; Prüfen ob bereits im PATH
        Push "$4"
        Push "$1\bin"
        Call StrContains
        Pop $5
        StrCmp $5 "" not_in_path

        DetailPrint "FFmpeg ist bereits im Benutzer-PATH enthalten."
        Goto path_update_done

        not_in_path:
            ; Neuen PATH zusammensetzen
            StrCmp $4 "" 0 path_not_empty
            StrCpy $4 "$1\bin"
            Goto write_path

            path_not_empty:
                StrCpy $4 "$4;$1\bin"

            write_path:
                WriteRegStr HKCU "Environment" "Path" "$4"
                DetailPrint "Benutzer-PATH erfolgreich aktualisiert."

                ; Environment-Update broadcasten
                DetailPrint "Sende Environment-Update an andere Prozesse..."
                System::Call 'User32::SendMessageTimeout(i 0xFFFF, i 0x1A, i 0, t "Environment", i 2, i 5000, i 0)'

        path_update_done:

    SetDetailsPrint lastused
SectionEnd

; --- Hilfsfunktion: String Contains ---
Function StrContains
    Exch $R1 ; $R1=search string
    Exch     ; swap with $R2
    Exch $R2 ; $R2=string to search (haystack)
    Push $R3
    Push $R4
    Push $R5
    Push $R6

    StrCpy $R3 0
    StrLen $R4 $R1
    StrLen $R5 $R2
    loop:
        StrCpy $R6 $R2 $R4 $R3
        StrCmp $R6 $R1 found
        StrCmp $R3 $R5 not_found
        IntOp $R3 $R3 + 1
        Goto loop

    found:
        StrCpy $R1 $R1
        Goto done

    not_found:
        StrCpy $R1 ""

    done:
        Pop $R6
        Pop $R5
        Pop $R4
        Pop $R3
        Pop $R2
        Exch $R1
FunctionEnd


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

    ; --- NEU: App nach Silent-Update neu starten ---
    ; Prüft, ob der Installer im Silent-Modus (/S) aufgerufen wurde.
    StrCmp $CMDLINE "/S" 0 not_silent
    ; Wir sind im Silent-Mode, also App neu starten
    ; Wir verwenden die Variable ${APP_EXE}, die oben definiert wurde.
    Exec '"$INSTDIR\${APP_EXE}"'
    not_silent:
    ; --- ENDE NEU ---

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
