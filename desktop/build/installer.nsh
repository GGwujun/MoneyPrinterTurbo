; MoneyPrinterTurbo — NSIS Installer Script
; Customizes the Windows installer produced by electron-builder.

!include "FileFunc.nsh"

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

; ── Installer sections ──────────────────────────────────────────────

Section "Install"
  SetOutPath "$INSTDIR"

  ; electron-builder already creates start menu + desktop shortcuts.
  ; Add extra uninstall registry metadata for Add/Remove Programs.

  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "DisplayName" "MoneyPrinterTurbo"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "Publisher" "MoneyPrinterTurbo"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "URLInfoAbout" "https://github.com/harry0703/MoneyPrinterTurbo"
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "NoRepair" 1

  ; Estimate install size for Add/Remove Programs
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}" "EstimatedSize" $0
SectionEnd

Section "Uninstall"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}"
SectionEnd
