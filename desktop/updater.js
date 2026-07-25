/**
 * MoneyPrinterTurbo Desktop — Auto-Updater Module
 *
 * Integrates electron-updater with GitHub Releases.
 * Checks for updates on startup, notifies user when available,
 * downloads in background, and installs on next restart.
 */

const { autoUpdater } = require("electron-updater");
const { dialog, app, BrowserWindow } = require("electron");
const log = require("electron-log");

// ---------------------------------------------------------------------------
// Configure electron-updater
// ---------------------------------------------------------------------------

autoUpdater.logger = log;
autoUpdater.autoDownload = false;       // Let user decide before downloading
autoUpdater.allowDowngrade = false;
autoUpdater.autoInstallOnAppQuit = true;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Check for updates silently on startup. If an update is found, emit an
 * event so the main process can show a notification banner.
 *
 * @param {Function} onUpdateAvailable  callback({ version, releaseNotes })
 * @param {Function} onError            callback(error)
 */
function checkForUpdates(onUpdateAvailable, onError) {
  autoUpdater.once("update-available", (info) => {
    log.info("Update available:", info.version);
    if (onUpdateAvailable) onUpdateAvailable(info);
  });

  autoUpdater.once("error", (err) => {
    log.warn("Update check failed:", err.message);
    if (onError) onError(err);
  });

  autoUpdater.checkForUpdates().catch((err) => {
    log.warn("Update check threw:", err.message);
  });
}

/**
 * Download the pending update. Notifies progress and completion.
 *
 * @param {BrowserWindow} win  main window for progress events
 */
function downloadUpdate(win) {
  autoUpdater.on("download-progress", (progress) => {
    if (win && !win.isDestroyed()) {
      win.webContents.send("update-download-progress", progress.percent);
    }
  });

  autoUpdater.once("update-downloaded", () => {
    if (win && !win.isDestroyed()) {
      win.webContents.send("update-downloaded");
    }
  });

  return autoUpdater.downloadUpdate();
}

/**
 * Prompt user to restart and install the update.
 *
 * @param {BrowserWindow} win  parent window for the dialog
 * @returns {Promise<boolean>}  true if user chose to install now
 */
async function promptInstall(win) {
  const result = await dialog.showMessageBox(win || undefined, {
    type: "info",
    title: "Update Ready",
    message: "A new version has been downloaded.",
    detail: "The update will be installed the next time you restart MoneyPrinterTurbo. Install now?",
    buttons: ["Restart Now", "Later"],
    defaultId: 0,
    cancelId: 1,
  });

  return result.response === 0;
}

/**
 * Trigger the installer — caller must have already stopped Streamlit.
 */
function quitAndInstall() {
  autoUpdater.quitAndInstall();
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

module.exports = {
  autoUpdater,
  checkForUpdates,
  downloadUpdate,
  promptInstall,
  quitAndInstall,
};
