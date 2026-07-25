; MoneyPrinterTurbo — NSIS Installer Script
; Customizes the Windows installer produced by electron-builder.

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

Section "Install"
  SetOutPath "$INSTDIR"

  ; Add extra metadata to Add/Remove Programs entries.
  ; electron-builder already creates the core uninstall registry keys,
  ; start menu shortcuts, and desktop shortcuts. Here we supplement with
  ; display metadata and read-only flags.
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "DisplayName" "MoneyPrinterTurbo"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "Publisher" "MoneyPrinterTurbo"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "URLInfoAbout" "https://github.com/harry0703/MoneyPrinterTurbo"
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "NoRepair" 1

  ; ${ESTIMATED_SIZE} is defined by electron-builder before including this script
  !ifdef ESTIMATED_SIZE
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "EstimatedSize" ${ESTIMATED_SIZE}
  !endif
SectionEnd

Section "Uninstall"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}"
SectionEnd
