; NSIS hooks for DharaSetup (per-user install).
; Keeps user data (%LOCALAPPDATA%\Dhara: database, backups, settings) on uninstall unless the user opts out.

!macro customInit
  ; Stop any running Dhara / bundled Postgres / Python from a previous install so files are not locked.
  IfFileExists "$INSTDIR\resources\helpers\stop-dhara-processes.ps1" 0 +2
    nsExec::Exec 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\helpers\stop-dhara-processes.ps1" -Root "$INSTDIR"'
!macroend

!macro customUnInit
  IfFileExists "$INSTDIR\resources\helpers\stop-dhara-processes.ps1" 0 +2
    nsExec::Exec 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\helpers\stop-dhara-processes.ps1" -Root "$INSTDIR"'
!macroend

!macro customUnInstall
  ; Silent uninstalls (including upgrades) always keep data.
  IfSilent keep_data

  MessageBox MB_YESNO|MB_ICONQUESTION \
    "Keep your Dhara catalogue data, backups and settings on this PC?$\r$\n$\r$\nChoose Yes to keep them (recommended — they are used again if you reinstall).$\r$\nChoose No to permanently delete %LOCALAPPDATA%\Dhara, including all backups." \
    IDYES keep_data IDNO wipe_data

  wipe_data:
    DetailPrint "Removing Dhara user data"
    SetShellVarContext current
    RMDir /r "$LOCALAPPDATA\Dhara"
    Goto done_uninst

  keep_data:
    DetailPrint "Keeping Dhara user data in $LOCALAPPDATA\Dhara"

  done_uninst:
!macroend
