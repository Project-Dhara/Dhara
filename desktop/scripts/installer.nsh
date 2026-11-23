; NSIS hooks for DharaSetup — keep data by default on uninstall.
!macro customUnInstall
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "Keep Dhara catalogue data and settings on this PC?$\r$\n$\r$\nChoose Yes to keep data (recommended). Choose No to remove Docker volumes and %LOCALAPPDATA%\Dhara." \
    IDYES keep_data IDNO wipe_data
  keep_data:
    DetailPrint "Keeping Dhara user data"
    Goto done_uninst
  wipe_data:
    DetailPrint "User chose to remove data — run: docker compose down -v (manual if Docker present)"
    RMDir /r "$LOCALAPPDATA\Dhara"
  done_uninst:
!macroend
