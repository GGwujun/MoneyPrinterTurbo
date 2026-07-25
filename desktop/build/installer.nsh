; MoneyPrinterTurbo — NSIS Installer Script
; Customizes the Windows installer produced by electron-builder.

!macro _mptBrand
  ; Brand the installer header with the app name.
  BrandingText "MoneyPrinterTurbo"
!macroend

!macro _mptWelcome
  ; Welcome page text.
  !insertmacro MUI_HEADER_TEXT "Welcome" "This will install MoneyPrinterTurbo on your computer.$\n$\nMoneyPrinterTurbo is an AI-powered short video generator. Just enter a topic and it will automatically create video scripts, find footage, generate voiceovers, add subtitles, and produce a high-definition short video."
!macroend

!macro _mptFinish
  ; Custom finish page: offer to launch the app.
  !define MUI_FINISHPAGE_RUN "$INSTDIR\MoneyPrinterTurbo.exe"
  !define MUI_FINISHPAGE_RUN_TEXT "Launch MoneyPrinterTurbo"
  !define MUI_FINISHPAGE_SHOWREADME ""
  !define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
  !define MUI_FINISHPAGE_LINK "View on GitHub"
  !define MUI_FINISHPAGE_LINK_LOCATION "https://github.com/harry0703/MoneyPrinterTurbo"
!macroend

; ── Installer sections ──────────────────────────────────────────────

Section "Install"
  SetOutPath "$INSTDIR"

  ; Create start menu shortcuts
  CreateDirectory "$SMPROGRAMS\MoneyPrinterTurbo"
  CreateShortCut "$SMPROGRAMS\MoneyPrinterTurbo\MoneyPrinterTurbo.lnk" "$INSTDIR\MoneyPrinterTurbo.exe"
  CreateShortCut "$SMPROGRAMS\MoneyPrinterTurbo\Uninstall MoneyPrinterTurbo.lnk" "$INSTDIR\Uninstall MoneyPrinterTurbo.exe"

  ; Desktop shortcut
  CreateShortCut "$DESKTOP\MoneyPrinterTurbo.lnk" "$INSTDIR\MoneyPrinterTurbo.exe"

  ; Write uninstall registry entries
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MoneyPrinterTurbo" "DisplayName" "MoneyPrinterTurbo"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MoneyPrinterTurbo" "UninstallString" '"$INSTDIR\Uninstall MoneyPrinterTurbo.exe"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MoneyPrinterTurbo" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MoneyPrinterTurbo" "Publisher" "MoneyPrinterTurbo"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MoneyPrinterTurbo" "URLInfoAbout" "https://github.com/harry0703/MoneyPrinterTurbo"
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MoneyPrinterTurbo" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MoneyPrinterTurbo" "NoRepair" 1

  ; Estimate size
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MoneyPrinterTurbo" "EstimatedSize" $0
SectionEnd

Section "Uninstall"
  ; Remove shortcuts
  Delete "$SMPROGRAMS\MoneyPrinterTurbo\MoneyPrinterTurbo.lnk"
  Delete "$SMPROGRAMS\MoneyPrinterTurbo\Uninstall MoneyPrinterTurbo.lnk"
  RMDir "$SMPROGRAMS\MoneyPrinterTurbo"
  Delete "$DESKTOP\MoneyPrinterTurbo.lnk"

  ; Remove registry
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MoneyPrinterTurbo"

  ; Remove install directory
  RMDir /r "$INSTDIR"
SectionEnd
