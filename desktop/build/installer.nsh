; MoneyPrinterTurbo — NSIS Installer Script
; Customizes the Windows installer produced by electron-builder.
; electron-builder handles uninstaller creation automatically when oneClick: false.

!macro _mptBrand
  BrandingText "MoneyPrinterTurbo"
!macroend

!macro _mptWelcome
  !insertmacro MUI_HEADER_TEXT "Welcome" "This will install MoneyPrinterTurbo on your computer.$\n$\nMoneyPrinterTurbo is an AI-powered short video generator. Enter a topic and it will automatically create scripts, find footage, generate voiceovers, add subtitles, and produce HD short videos."
!macroend

!macro _mptFinish
  !define MUI_FINISHPAGE_RUN "$INSTDIR\MoneyPrinterTurbo.exe"
  !define MUI_FINISHPAGE_RUN_TEXT "Launch MoneyPrinterTurbo"
  !define MUI_FINISHPAGE_LINK "View on GitHub"
  !define MUI_FINISHPAGE_LINK_LOCATION "https://github.com/harry0703/MoneyPrinterTurbo"
!macroend

; ── customInstall ────────────────────────────────────────────────────
; Called by electron-builder during install. Add registry metadata for
; Add/Remove Programs beyond what electron-builder writes automatically.

!macro customInstall
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "DisplayName" "MoneyPrinterTurbo"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "Publisher" "MoneyPrinterTurbo"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "URLInfoAbout" "https://github.com/harry0703/MoneyPrinterTurbo"
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "NoRepair" 1
  !ifdef ESTIMATED_SIZE
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "EstimatedSize" ${ESTIMATED_SIZE}
  !endif
!macroend
