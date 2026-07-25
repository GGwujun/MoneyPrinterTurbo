/**
 * MoneyPrinterTurbo Desktop — Preload Script
 *
 * This runs before the renderer process and exposes a minimal, safe
 * API via contextBridge. Streamlit itself does NOT use this API —
 * it's available for future shell enhancements (custom title bar,
 * native notifications, etc.).
 */

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("mptDesktop", {
  /** Returns { running: bool, port: number|null, pid: number|null } */
  getPythonStatus: () => ipcRenderer.invoke("get-python-status"),

  /** Returns the active Streamlit URL (e.g. http://127.0.0.1:8501) */
  getStreamlitUrl: () => ipcRenderer.invoke("get-streamlit-url"),

  /** Restart the Python backend. Returns true on success. */
  restartPython: () => ipcRenderer.invoke("restart-python"),

  /** Returns the desktop app version string. */
  getAppVersion: () => ipcRenderer.invoke("get-app-version"),

  /** Listen for Python process status changes. */
  onPythonStatusChange: (callback) => {
    const handler = (_event, status) => callback(status);
    ipcRenderer.on("python-status-changed", handler);
    // Return a cleanup function
    return () => ipcRenderer.removeListener("python-status-changed", handler);
  },
});
