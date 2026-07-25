/**
 * MoneyPrinterTurbo Desktop — Electron Main Process
 *
 * Manages the full lifecycle:
 *   1. First-launch onboarding wizard (pre-flight checks + LLM config)
 *   2. Python / Streamlit child-process management
 *   3. Application menu with Help → Check for Updates
 *   4. Auto-update via electron-updater (GitHub Releases)
 *   5. Main BrowserWindow loading Streamlit UI
 */

const {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  shell,
} = require("electron");
const path = require("node:path");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const { spawn, exec, execSync } = require("node:child_process");

// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------

try {
  const log = require("electron-log");
  log.transports.file.resolvePathFn = () =>
    path.join(app.getPath("userData"), "logs", "electron.log");
  module.exports.log = log;
  var logger = log;
} catch {
  var logger = {
    info: (...a) => console.log("[INFO]", ...a),
    warn: (...a) => console.warn("[WARN]", ...a),
    error: (...a) => console.error("[ERROR]", ...a),
    debug: (...a) => console.debug("[DEBUG]", ...a),
  };
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STREAMLIT_PORT_START = 8501;
const STREAMLIT_PORT_END = 8599;
const SERVER_READY_TIMEOUT_MS = 120_000;
const SERVER_POLL_INTERVAL_MS = 500;
const WINDOW_WIDTH = 1400;
const WINDOW_HEIGHT = 900;
const WINDOW_MIN_WIDTH = 900;
const WINDOW_MIN_HEIGHT = 600;
const ONBOARDING_WIDTH = 640;
const ONBOARDING_HEIGHT = 520;

// ---------------------------------------------------------------------------
// Path resolution
// ---------------------------------------------------------------------------

/** Absolute path to the project root. */
function projectRoot() {
  return path.resolve(__dirname, "..");
}

const IS_WIN = process.platform === "win32";
const IS_MAC = process.platform === "darwin";
const IS_PACKAGED = app.isPackaged;

// In packaged builds, Python code is in process.resourcesPath
function appResourcesPath() {
  return IS_PACKAGED ? process.resourcesPath : projectRoot();
}

// ---------------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------------

let streamlitProcess = null;
let streamlitPort = null;
let mainWindow = null;
let splashWindow = null;
let onboardingWindow = null;
let isQuitting = false;
let updatePendingInfo = null;
let streamlitCrashCount = 0;
const MAX_AUTO_RESTART = 2;  // auto-restart up to 2 times before showing dialog

// ---------------------------------------------------------------------------
// Python / uv discovery
// ---------------------------------------------------------------------------

function findPython() {
  const resources = appResourcesPath();

  // 1) Bundled .venv in resources (production)
  const bundledPython = IS_WIN
    ? path.join(resources, ".venv", "Scripts", "python.exe")
    : path.join(resources, ".venv", "bin", "python3");
  if (fs.existsSync(bundledPython)) {
    logger.info("Found bundled Python:", bundledPython);
    return bundledPython;
  }

  // 2) Project .venv (development)
  const root = projectRoot();
  const venvPython = IS_WIN
    ? path.join(root, ".venv", "Scripts", "python.exe")
    : path.join(root, ".venv", "bin", "python3");
  if (fs.existsSync(venvPython)) {
    logger.info("Found Python in .venv:", venvPython);
    return venvPython;
  }

  // 3) uv on PATH
  try {
    execSync(IS_WIN ? "uv.exe --version" : "uv --version", {
      timeout: 5000,
      stdio: "ignore",
    });
    logger.info("Using uv run python");
    return "uv";
  } catch {
    // uv not available
  }

  return null;
}

// ---------------------------------------------------------------------------
// Port discovery
// ---------------------------------------------------------------------------

function portIsAvailable(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close();
      resolve(true);
    });
    server.listen(port, "127.0.0.1");
  });
}

async function findAvailablePort() {
  for (let p = STREAMLIT_PORT_START; p <= STREAMLIT_PORT_END; p++) {
    if (await portIsAvailable(p)) {
      logger.info(`Selected port: ${p}`);
      return p;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Server health check
// ---------------------------------------------------------------------------

function checkServerReady(url) {
  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      resolve(res.statusCode < 500);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(2000, () => { req.destroy(); resolve(false); });
  });
}

function waitForServer(url, timeoutMs = SERVER_READY_TIMEOUT_MS) {
  const start = Date.now();
  return new Promise((resolve) => {
    function poll() {
      if (isQuitting) { resolve(false); return; }
      checkServerReady(url).then((ready) => {
        if (ready) {
          logger.info(`Server ready at ${url} (${Date.now() - start}ms)`);
          resolve(true);
        } else if (Date.now() - start > timeoutMs) {
          logger.error(`Server timeout at ${url}`);
          resolve(false);
        } else {
          setTimeout(poll, SERVER_POLL_INTERVAL_MS);
        }
      });
    }
    poll();
  });
}

// ---------------------------------------------------------------------------
// Streamlit child-process management
// ---------------------------------------------------------------------------

function buildStreamlitEnv() {
  const resources = appResourcesPath();
  return {
    ...process.env,
    PYTHONPATH: resources,
    MPT_ROOT_DIR: resources,
    MPT_WEBUI_HOST: "127.0.0.1",
    MPT_WEBUI_PORT: String(streamlitPort),
    PYTHONUNBUFFERED: "1",
    PYTHONIOENCODING: "utf-8",
  };
}

function buildStreamlitArgs(port) {
  return [
    "-m", "streamlit", "run", "webui/Main.py",
    "--server.address=127.0.0.1",
    `--server.port=${port}`,
    "--browser.serverAddress=127.0.0.1",
    "--browser.gatherUsageStats=false",
    "--client.toolbarMode=minimal",
    "--logger.hideWelcomeMessage=true",
    "--server.showEmailPrompt=false",
    "--server.enableCORS=true",
    "--server.headless=true",
    "--server.fileWatcherType=none",
  ];
}

function startStreamlit() {
  const python = findPython();
  if (!python) {
    dialog.showErrorBox(
      "Python Not Found",
      "Python 3.11+ or uv is required to run MoneyPrinterTurbo.\n\n" +
        "Install Python from https://python.org or uv from https://docs.astral.sh/uv\n" +
        "Then run: uv sync --frozen"
    );
    app.quit();
    return null;
  }

  const resources = appResourcesPath();
  const env = buildStreamlitEnv();
  const args = buildStreamlitArgs(streamlitPort);

  logger.info(`Starting Streamlit on port ${streamlitPort}...`);
  logger.info(`Python: ${python}  Args: ${args.join(" ")}`);

  let proc;
  if (python === "uv") {
    proc = spawn("uv", ["run", "python", ...args], {
      cwd: resources, env,
      stdio: ["ignore", "pipe", "pipe"],
      shell: IS_WIN,
    });
  } else {
    proc = spawn(python, args, {
      cwd: resources, env,
      stdio: ["ignore", "pipe", "pipe"],
      shell: false,
    });
  }
  attachProcessListeners(proc);
  return proc;
}

function attachProcessListeners(proc) {
  proc.stdout?.on("data", (d) => process.stdout.write(d));
  proc.stderr?.on("data", (d) => process.stderr.write(d));
  proc.on("error", (err) => logger.error("Streamlit process error:", err.message));

  proc.on("exit", (code, signal) => {
    logger.info(`Streamlit exited (code=${code}, signal=${signal})`);
    streamlitProcess = null;

    if (isQuitting) return;

    // Clean exit — reset crash counter
    if (code === 0 || signal === "SIGTERM" || signal === "SIGINT") {
      streamlitCrashCount = 0;
      return;
    }

    streamlitCrashCount++;
    logger.warn(`Streamlit crashed (attempt ${streamlitCrashCount}/${MAX_AUTO_RESTART})`);

    if (streamlitCrashCount <= MAX_AUTO_RESTART) {
      logger.info("Auto-restarting Streamlit...");
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.executeJavaScript(
          `document.body.insertAdjacentHTML('afterbegin',
            '<div style="position:fixed;top:0;left:0;right:0;z-index:99999;background:#1a1a2e;color:#e0e0e0;padding:10px 16px;font-size:13px;text-align:center;font-family:sans-serif">' +
            '⚠ Backend restarted — recovering...</div>')`
        ).catch(() => {});
      }
      setTimeout(() => restartApp(), 1000);
      return;
    }

    streamlitCrashCount = 0;
    const parent = (mainWindow && !mainWindow.isDestroyed()) ? mainWindow : undefined;
    dialog.showMessageBox(parent, {
      type: "error",
      title: "Backend Stopped",
      message: "The Python backend stopped unexpectedly after multiple attempts.",
      detail: `Exit code: ${code ?? "none"}, signal: ${signal ?? "none"}\n\nCheck logs for details.`,
      buttons: ["Restart", "Quit"],
      defaultId: 0,
    }).then(({ response }) => {
      if (response === 0) restartApp();
      else app.quit();
    });
  });
}

function stopStreamlit() {
  if (!streamlitProcess) return;
  logger.info("Stopping Streamlit...");
  if (IS_WIN) {
    try { exec(`taskkill /PID ${streamlitProcess.pid} /T /F`); } catch {}
  } else {
    streamlitProcess.kill("SIGTERM");
    setTimeout(() => {
      if (streamlitProcess) streamlitProcess.kill("SIGKILL");
    }, 5000);
  }
}

// ---------------------------------------------------------------------------
// Window management — splash
// ---------------------------------------------------------------------------

const SPLASH_HTML = `<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0f1117;color:#e0e0e0;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;-webkit-app-region:drag;user-select:none}
  .logo{font-size:22px;font-weight:700;margin-bottom:24px;letter-spacing:-0.3px}
  .logo span{color:#4fc3f7}
  .spinner{width:32px;height:32px;border:3px solid #333;border-top-color:#4fc3f7;border-radius:50%;animation:spin .8s linear infinite;margin-bottom:20px}
  @keyframes spin{to{transform:rotate(360deg)}}
  .status{font-size:13px;color:#888}
</style></head>
<body>
<div class="logo">MoneyPrinter<span>Turbo</span></div>
<div class="spinner"></div>
<div class="status">Starting Python backend…</div>
</body></html>`;

function createSplashWindow() {
  splashWindow = new BrowserWindow({
    width: 480, height: 320,
    frame: false, transparent: false, resizable: false, center: true,
    show: false, backgroundColor: "#0f1117",
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  splashWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(SPLASH_HTML)}`);
  splashWindow.once("ready-to-show", () => splashWindow.show());
}

// ---------------------------------------------------------------------------
// Window management — main
// ---------------------------------------------------------------------------

function createMainWindow(url) {
  mainWindow = new BrowserWindow({
    width: WINDOW_WIDTH, height: WINDOW_HEIGHT,
    minWidth: WINDOW_MIN_WIDTH, minHeight: WINDOW_MIN_HEIGHT,
    title: "MoneyPrinterTurbo",
    backgroundColor: "#0f1117",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.loadURL(url);

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith("http://127.0.0.1") && !url.startsWith("http://localhost")) {
      shell.openExternal(url);
    }
    return { action: "deny" };
  });

  mainWindow.webContents.on("will-navigate", (event, navUrl) => {
    const p = new URL(navUrl);
    if (p.hostname !== "127.0.0.1" && p.hostname !== "localhost") {
      event.preventDefault();
      shell.openExternal(navUrl);
    }
  });

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.close();
      splashWindow = null;
    }
    // Send update info to renderer for notification banner
    if (updatePendingInfo && mainWindow) {
      mainWindow.webContents.send("update-available", updatePendingInfo);
    }
  });

  mainWindow.on("closed", () => { mainWindow = null; });
}

// ---------------------------------------------------------------------------
// Onboarding wizard
// ---------------------------------------------------------------------------

const ONBOARDING_HTML = `<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<style>
  :root{--bg:#13161b;--card:#1c1f28;--text:#d0d2d7;--muted:#7c8190;--accent:#4fc3f7;--green:#66bb6a;--red:#ef5350;--border:#2a2e38;--input-bg:#242834}
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);height:100vh;display:flex;align-items:center;justify-content:center}
  .wizard{width:100%;max-width:560px;padding:20px}
  .steps{display:flex;gap:4px;margin-bottom:28px}
  .step{flex:1;height:3px;background:var(--border);border-radius:2px;transition:background .3s}
  .step.active{background:var(--accent)}
  .step.done{background:var(--green)}
  .page{display:none;animation:fadeIn .3s ease}
  .page.active{display:block}
  @keyframes fadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
  h2{font-size:22px;font-weight:700;margin-bottom:8px}
  .desc{color:var(--muted);font-size:14px;margin-bottom:24px;line-height:1.5}
  .check-item{display:flex;align-items:center;gap:10px;padding:12px 16px;background:var(--card);border-radius:8px;margin-bottom:8px;font-size:14px}
  .check-icon{font-size:18px}
  .check-icon.ok{color:var(--green)} .check-icon.fail{color:var(--red)} .check-icon.wait{color:var(--muted)}
  .check-label{flex:1} .check-detail{font-size:12px;color:var(--muted)}
  label{display:block;font-size:13px;font-weight:600;margin-bottom:4px;color:var(--muted)}
  input,select{width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:6px;background:var(--input-bg);color:var(--text);font-size:14px;margin-bottom:16px;outline:none;transition:border-color .2s}
  input:focus,select:focus{border-color:var(--accent)}
  .hint{font-size:12px;color:var(--muted);margin-top:-12px;margin-bottom:16px}
  .hint a{color:var(--accent);text-decoration:none}.hint a:hover{text-decoration:underline}
  .actions{display:flex;justify-content:flex-end;gap:10px;margin-top:8px}
  button{padding:10px 24px;border-radius:6px;font-size:14px;font-weight:600;cursor:pointer;border:none;transition:all .2s}
  button:hover{opacity:.9}
  button:disabled{opacity:.4;cursor:default}
  .btn-primary{background:var(--accent);color:#000}
  .btn-secondary{background:var(--card);color:var(--text);border:1px solid var(--border)}
  .btn-test{font-size:12px;padding:6px 14px}
  .test-result{font-size:12px;margin-top:-12px;margin-bottom:12px;padding:6px 10px;border-radius:4px}
  .test-result.ok{background:rgba(102,187,106,.1);color:var(--green)}.test-result.fail{background:rgba(239,83,80,.1);color:var(--red)}
  .summary-item{display:flex;align-items:center;gap:8px;padding:6px 0;font-size:14px}
  .summary-icon{font-size:18px}
</style></head>
<body>
<div class="wizard">
  <div class="steps">
    <div class="step active" id="step1"></div>
    <div class="step" id="step2"></div>
    <div class="step" id="step3"></div>
    <div class="step" id="step4"></div>
  </div>

  <!-- Page 1: Welcome -->
  <div class="page active" id="p1">
    <h2>🎬 Welcome to MoneyPrinterTurbo</h2>
    <p class="desc">AI-powered short video generator. Enter a topic, and it automatically creates scripts, finds footage, generates voiceovers, adds subtitles, and produces HD short videos.</p>
    <p class="desc">This quick setup will check your system and help configure the AI model key. Everything is saved locally — your data never leaves your machine.</p>
    <div class="actions"><button class="btn-primary" onclick="goPage(2)">Get Started →</button></div>
  </div>

  <!-- Page 2: System Check -->
  <div class="page" id="p2">
    <h2>✅ System Check</h2>
    <p class="desc">Verifying required tools are installed on your computer.</p>
    <div class="check-item"><span class="check-icon wait" id="py-icon">⏳</span><span class="check-label">Python 3.11+</span><span class="check-detail" id="py-ver"></span></div>
    <div class="check-item"><span class="check-icon wait" id="ff-icon">⏳</span><span class="check-label">FFmpeg</span><span class="check-detail" id="ff-ver"></span></div>
    <div class="check-item"><span class="check-icon wait" id="deps-icon">⏳</span><span class="check-label">Python Dependencies</span><span class="check-detail" id="deps-ver"></span></div>
    <div class="actions">
      <button class="btn-secondary" onclick="goPage(1)">← Back</button>
      <button class="btn-primary" id="btn-sys-next" disabled onclick="goPage(3)">Next →</button>
    </div>
  </div>

  <!-- Page 3: LLM Config -->
  <div class="page" id="p3">
    <h2>🔑 AI Model Setup</h2>
    <p class="desc">MoneyPrinterTurbo needs an LLM to generate video scripts. Choose a provider and enter your API key.</p>
    <label for="provider">Provider</label>
    <select id="provider"></select>
    <label for="apikey">API Key</label>
    <input type="password" id="apikey" placeholder="sk-...">
    <div class="hint" id="provider-hint"></div>
    <div id="test-llm-result"></div>
    <div class="actions">
      <button class="btn-secondary" onclick="goPage(2)">← Back</button>
      <button class="btn-secondary btn-test" id="btn-test" onclick="testLLM()">Test Connection</button>
      <button class="btn-primary" id="btn-llm-next" onclick="goPage(4)">Skip / Next →</button>
    </div>
  </div>

  <!-- Page 4: Done -->
  <div class="page" id="p4">
    <h2>🚀 Ready to Go!</h2>
    <p class="desc">Everything is set up. Here's a summary:</p>
    <div class="summary-item"><span class="summary-icon">✅</span> Python — <span id="sum-python"></span></div>
    <div class="summary-item"><span class="summary-icon">✅</span> FFmpeg — <span id="sum-ffmpeg"></span></div>
    <div class="summary-item"><span class="summary-icon">🔑</span> LLM — <span id="sum-llm"></span></div>
    <p class="desc" style="margin-top:16px">Your config is saved locally in <code>config.toml</code>. You can change settings anytime from the app.</p>
    <div class="actions"><button class="btn-primary" id="btn-launch" onclick="finish()">Launch App</button></div>
  </div>
</div>
<script>
  const { ipcRenderer } = require("electron");
  let currentPage = 2;

  function setStep(n){["step1","step2","step3","step4"].forEach((s,i)=>{
    const el=document.getElementById(s);
    el.classList.remove("active","done");
    if(i+1<n) el.classList.add("done");
    if(i+1===n) el.classList.add("active");
  })}
  function goPage(n){
    document.querySelectorAll(".page").forEach(p=>p.classList.remove("active"));
    document.getElementById("p"+n).classList.add("active");
    setStep(n); currentPage=n;
    if(n===2) runChecks();
  }

  // —— Page 2: System checks ——
  async function runChecks(){
    setCheck("py-icon","wait","py-ver","Checking...");
    setCheck("ff-icon","wait","ff-ver","Checking...");
    setCheck("deps-icon","wait","deps-ver","Checking...");
    document.getElementById("btn-sys-next").disabled=true;

    const py = await ipcRenderer.invoke("check-python");
    setCheck("py-icon", py.ok?"ok":"fail", "py-ver", py.version||"Not found");
    document.getElementById("sum-python").textContent=py.version||"Not found";

    const ff = await ipcRenderer.invoke("check-ffmpeg");
    setCheck("ff-icon", ff.ok?"ok":"fail", "ff-ver", ff.version||"Not found");
    document.getElementById("sum-ffmpeg").textContent=ff.version||"Not found";

    const deps = await ipcRenderer.invoke("check-deps");
    setCheck("deps-icon", deps.ok?"ok":"fail", "deps-ver", deps.ok?"Installed":"Missing");

    document.getElementById("btn-sys-next").disabled=!py.ok;
  }
  function setCheck(iconId, state, detailId, text){
    const icons={ok:"✅",fail:"❌",wait:"⏳"};
    document.getElementById(iconId).textContent=icons[state];
    document.getElementById(iconId).className="check-icon "+state;
    document.getElementById(detailId).textContent=text;
  }

  // —— Page 3: LLM config ——
  async function initProviders(){
    const providers = await ipcRenderer.invoke("get-providers");
    const sel = document.getElementById("provider");
    providers.forEach(p=>{
      const opt = document.createElement("option");
      opt.value=p.id; opt.textContent=p.label;
      sel.appendChild(opt);
    });
    sel.onchange=()=>{
      const p=providers.find(x=>x.id===sel.value);
      document.getElementById("provider-hint").innerHTML=
        p.apiKeyUrl?'<a href="'+p.apiKeyUrl+'" target="_blank">Get API key →</a>':'';
    };
    sel.dispatchEvent(new Event("change"));
    document.getElementById("sum-llm").textContent="Not configured";
  }
  async function testLLM(){
    const btn=document.getElementById("btn-test");
    btn.disabled=true; btn.textContent="Testing...";
    const r=document.getElementById("test-llm-result");
    const provider=document.getElementById("provider").value;
    const apikey=document.getElementById("apikey").value;
    try{
      const res = await ipcRenderer.invoke("test-llm", {provider, apiKey:apikey});
      r.innerHTML='<div class="test-result ok">✓ Connected in '+res.elapsed+'s</div>';
      btn.textContent="✓ Connected"; btn.style.color="var(--green)";
    }catch(e){
      r.innerHTML='<div class="test-result fail">✗ '+e.message+'</div>';
      btn.disabled=false; btn.textContent="Retry Connection Test";
    }
  }
  async function finish(){
    const provider=document.getElementById("provider").value;
    const apikey=document.getElementById("apikey").value;
    await ipcRenderer.invoke("complete-onboarding", {provider, apiKey:apikey});
  }
  goPage(1);
  initProviders();
  ipcRenderer.on("sys-checks-done",(_,r)=>{
    setCheck("py-icon",r.pythonOk?"ok":"fail","py-ver",r.pythonVer||"Not found");
    setCheck("ff-icon",r.ffmpegOk?"ok":"fail","ff-ver",r.ffmpegVer||"Not found");
    setCheck("deps-icon",r.depsOk?"ok":"fail","deps-ver",r.depsOk?"Installed":"Missing");
    document.getElementById("btn-sys-next").disabled=!r.pythonOk;
  });
</script></body></html>`;

function createOnboardingWindow() {
  onboardingWindow = new BrowserWindow({
    width: ONBOARDING_WIDTH, height: ONBOARDING_HEIGHT,
    resizable: false, center: true, show: false,
    title: "MoneyPrinterTurbo — Setup",
    backgroundColor: "#13161b",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: false,   // onboarding uses ipcRenderer directly
      nodeIntegration: true,     // onboardingRenderer needs require("electron")
      sandbox: false,
    },
  });

  onboardingWindow.loadURL(
    `data:text/html;charset=utf-8,${encodeURIComponent(ONBOARDING_HTML)}`
  );
  onboardingWindow.once("ready-to-show", () => onboardingWindow.show());
  onboardingWindow.on("closed", () => { onboardingWindow = null; });
}

// ---------------------------------------------------------------------------
// Auto-update integration
// ---------------------------------------------------------------------------

let updater = null;
try { updater = require("./updater"); } catch (e) {
  logger.warn("updater.js could not be loaded:", e.message);
}

function startAutoUpdate() {
  if (!updater) return;

  setTimeout(() => {
    updater.checkForUpdates(
      (info) => {
        // Update available — store info and notify main window
        updatePendingInfo = { version: info.version, releaseNotes: info.releaseNotes };
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send("update-available", updatePendingInfo);
        }
      },
      (err) => {
        logger.warn("Auto-update check failed:", err.message);
      }
    );
  }, 5000); // Delay 5s after app start to avoid competing with Streamlit startup
}

// ---------------------------------------------------------------------------
// IPC handlers
// ---------------------------------------------------------------------------

function registerIpcHandlers() {
  ipcMain.handle("get-python-status", () => ({
    running: streamlitProcess !== null && streamlitProcess.exitCode === null,
    port: streamlitPort,
    pid: streamlitProcess?.pid ?? null,
  }));

  ipcMain.handle("get-streamlit-url", () =>
    streamlitPort ? `http://127.0.0.1:${streamlitPort}` : null
  );

  ipcMain.handle("restart-python", async () => {
    restartApp();
    return true;
  });

  ipcMain.handle("get-app-version", () => app.getVersion());

  // ── Onboarding handlers ──

  ipcMain.handle("check-python", async () => {
    const python = findPython();
    if (!python) return { ok: false, version: "Not found" };
    try {
      const cmd = python === "uv" ? "uv" : python;
      const args = python === "uv" ? ["run", "python", "--version"] : ["--version"];
      const result = execSync(`${cmd} ${args.join(" ")}`, { timeout: 10000 });
      return { ok: true, version: result.toString().trim() };
    } catch {
      return { ok: false, version: "Could not run" };
    }
  });

  ipcMain.handle("check-ffmpeg", async () => {
    try {
      const result = execSync("ffmpeg -version", { timeout: 10000 });
      const firstLine = result.toString().split("\n")[0].trim();
      return { ok: true, version: firstLine };
    } catch {
      return { ok: false, version: "Not found — install from https://ffmpeg.org" };
    }
  });

  ipcMain.handle("check-deps", async () => {
    try {
      const python = findPython();
      const cmd = python === "uv" ? "uv" : python;
      const args = python === "uv"
        ? ["run", "python", "-c", "import streamlit, toml, loguru"]
        : ["-c", "import streamlit, toml, loguru"];
      // spawnSync avoids shell quoting issues with -c argument
      const result = require("node:child_process").spawnSync(cmd, args, {
        timeout: 15000,
        shell: false,
        windowsHide: true,
      });
      return { ok: result.status === 0 };
    } catch {
      return { ok: false };
    }
  });

  ipcMain.handle("get-providers", () => {
    return [
      { id: "moonshot", label: "Kimi / Moonshot AI", apiKeyUrl: "https://platform.kimi.com/console/api-keys" },
      { id: "openai", label: "OpenAI", apiKeyUrl: "https://platform.openai.com/api-keys" },
      { id: "deepseek", label: "DeepSeek", apiKeyUrl: "https://platform.deepseek.com/api_keys" },
      { id: "gemini", label: "Google Gemini", apiKeyUrl: "https://aistudio.google.com/app/apikey" },
      { id: "qwen", label: "Alibaba Cloud Qwen", apiKeyUrl: "https://dashscope.console.aliyun.com/apiKey" },
      { id: "grok", label: "xAI Grok", apiKeyUrl: "https://console.x.ai/" },
      { id: "ollama", label: "Ollama (Local)", apiKeyUrl: "" },
    ];
  });

  ipcMain.handle("test-llm", async (_event, { provider, apiKey }) => {
    const python = findPython();
    if (!python) throw new Error("Python not found");

    const scriptPath = path.join(__dirname, "scripts", "set_config.py");
    const configPath = path.join(appResourcesPath(), "config.toml");

    // Write the API key to config first
    const setArgs = [
      scriptPath, "--config", configPath, "set",
      "__section__.app",
      `llm_provider=${provider}\n${provider}_api_key=${apiKey}`
    ];
    const cmd = python === "uv" ? "uv" : python;
    const prefix = python === "uv" ? ["run", "python"] : [];
    try {
      execSync([cmd, ...prefix, ...setArgs].join(" "), { timeout: 10000, stdio: "ignore" });
    } catch (e) {
      throw new Error("Failed to write config: " + e.message);
    }

    // Test the connection
    try {
      const testArgs = [scriptPath, "--config", configPath, "test-llm", "--provider", provider];
      const result = execSync([cmd, ...prefix, ...testArgs].join(" "), { timeout: 30000, encoding: "utf8" });
      const match = result.match(/ok (\d+\.\d+)s/);
      if (match) return { elapsed: parseFloat(match[1]) };
      throw new Error(result.trim());
    } catch (e) {
      throw new Error(e.stderr || e.stdout || e.message);
    }
  });

  ipcMain.handle("complete-onboarding", async (_event, { provider, apiKey }) => {
    if (apiKey && provider) {
      const python = findPython();
      if (python) {
        const scriptPath = path.join(__dirname, "scripts", "set_config.py");
        const configPath = path.join(appResourcesPath(), "config.toml");
        const setArgs = [
          scriptPath, "--config", configPath, "set",
          "__section__.app",
          `llm_provider=${provider}\n${provider}_api_key=${apiKey}`
        ];
        const cmd = python === "uv" ? "uv" : python;
        const prefix = python === "uv" ? ["run", "python"] : [];
        try {
          execSync([cmd, ...prefix, ...setArgs].join(" "), { timeout: 10000, stdio: "ignore" });
        } catch { /* non-fatal */ }
      }
    }

    // Write marker so onboarding doesn't show again
    fs.writeFileSync(path.join(app.getPath("userData"), "onboarded"), new Date().toISOString());

    // Close onboarding, proceed to splash → main
    if (onboardingWindow && !onboardingWindow.isDestroyed()) {
      onboardingWindow.close();
      onboardingWindow = null;
    }

    logger.info("Onboarding complete — launching app");
    launchApp();
  });

  // ── Update handlers ──

  ipcMain.handle("check-for-update", async () => {
    if (!updater) return { error: "Updater not available" };
    try {
      const result = await updater.autoUpdater.checkForUpdates();
      if (result?.updateInfo?.version) {
        return { updateAvailable: true, version: result.updateInfo.version };
      }
      return { updateAvailable: false };
    } catch (e) {
      return { error: e.message };
    }
  });

  ipcMain.handle("download-update", async () => {
    if (!updater) throw new Error("Updater not available");
    await updater.downloadUpdate(mainWindow);
    return true;
  });

  ipcMain.handle("install-update", async () => {
    await updater.promptInstall(mainWindow);
    return true;
  });
}

// ---------------------------------------------------------------------------
// Application menu
// ---------------------------------------------------------------------------

function buildAppMenu() {
  const template = [];

  if (IS_MAC) {
    template.push({
      label: "MoneyPrinterTurbo",
      submenu: [
        { role: "about" },
        { type: "separator" },
        { role: "services" },
        { type: "separator" },
        { role: "hide" },
        { role: "hideOthers" },
        { role: "unhide" },
        { type: "separator" },
        { role: "quit" },
      ],
    });
  }

  template.push(
    {
      label: "File",
      submenu: [
        {
          label: "Settings",
          accelerator: IS_MAC ? "Cmd+," : "Ctrl+,",
          click: () => {
            if (mainWindow) {
              mainWindow.webContents.executeJavaScript(
                'document.querySelector(\'button[kind="secondary"]\')?.click?.()'
              ).catch(() => {});
            }
          },
        },
        { type: "separator" },
        IS_MAC ? { role: "close" } : { role: "quit" },
      ],
    },
    {
      label: "Edit",
      submenu: [
        { role: "undo" }, { role: "redo" }, { type: "separator" },
        { role: "cut" }, { role: "copy" }, { role: "paste" },
        { role: "selectAll" },
      ],
    },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "forceReload" },
        { role: "toggleDevTools" },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { type: "separator" },
        { role: "togglefullscreen" },
      ],
    },
    {
      label: "Help",
      submenu: [
        {
          label: "Check for Updates...",
          click: async () => {
            if (!updater) {
              dialog.showMessageBox(mainWindow || undefined, {
                type: "info",
                message: "Auto-update is not available in this build.",
                detail: "Download the latest version from GitHub Releases.",
              });
              return;
            }
            try {
              const result = await updater.autoUpdater.checkForUpdates();
              if (result?.updateInfo?.version) {
                const resp = await dialog.showMessageBox(mainWindow || undefined, {
                  type: "info",
                  title: "Update Available",
                  message: `Version ${result.updateInfo.version} is available.`,
                  detail: "Would you like to download it now?",
                  buttons: ["Download", "Later"],
                  defaultId: 0,
                });
                if (resp.response === 0) {
                  await updater.downloadUpdate(mainWindow);
                  await updater.promptInstall(mainWindow);
                }
              } else {
                dialog.showMessageBox(mainWindow || undefined, {
                  type: "info",
                  message: "You're up to date!",
                  detail: `MoneyPrinterTurbo v${app.getVersion()} is the latest version.`,
                });
              }
            } catch (e) {
              dialog.showErrorBox("Update Check Failed", e.message);
            }
          },
        },
        { type: "separator" },
        {
          label: "GitHub Repository",
          click: () => shell.openExternal("https://github.com/harry0703/MoneyPrinterTurbo"),
        },
        {
          label: "Report an Issue",
          click: () => shell.openExternal("https://github.com/harry0703/MoneyPrinterTurbo/issues"),
        },
        { type: "separator" },
        { role: "about" },
      ],
    }
  );

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

function restartApp() {
  stopStreamlit();
  streamlitPort = null;
  launchApp();
}

async function launchApp() {
  // Check for first-launch onboarding
  const onboardedFile = path.join(app.getPath("userData"), "onboarded");
  if (!fs.existsSync(onboardedFile)) {
    createOnboardingWindow();
    return; // The onboarding completion handler will call launchApp()
  }

  // Find a free port
  const port = await findAvailablePort();
  if (!port) {
    dialog.showErrorBox(
      "No Port Available",
      `All ports ${STREAMLIT_PORT_START}–${STREAMLIT_PORT_END} are in use.`
    );
    app.quit();
    return;
  }
  streamlitPort = port;

  // Show splash while Python starts
  createSplashWindow();

  // Start Python / Streamlit
  streamlitProcess = startStreamlit();
  if (!streamlitProcess) return;

  // Wait for Streamlit to be ready
  const streamlitUrl = `http://127.0.0.1:${streamlitPort}`;
  const ready = await waitForServer(streamlitUrl + "/healthz");

  if (ready) {
    createMainWindow(streamlitUrl);
    // Check for updates once Streamlit is loaded
    startAutoUpdate();
  } else if (!isQuitting) {
    if (splashWindow && !splashWindow.isDestroyed()) { splashWindow.close(); splashWindow = null; }
    dialog.showErrorBox(
      "Startup Timeout",
      "Streamlit did not start within 2 minutes.\n\n" +
        "Check that Python and dependencies are installed:\n  uv sync --frozen"
    );
    app.quit();
  }
}

// ---------------------------------------------------------------------------
// Single-instance lock
// ---------------------------------------------------------------------------

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}

// ---------------------------------------------------------------------------
// App event handlers
// ---------------------------------------------------------------------------

app.whenReady().then(() => {
  logger.info("MoneyPrinterTurbo Desktop starting...");
  buildAppMenu();
  registerIpcHandlers();
  launchApp();
});

app.on("before-quit", () => {
  isQuitting = true;
  stopStreamlit();
});

app.on("window-all-closed", () => {
  if (!IS_MAC) app.quit();
});

app.on("activate", () => {
  if (!mainWindow && !isQuitting) launchApp();
});

process.on("uncaughtException", (err) => {
  logger.error("Uncaught:", err.stack || err.message);
});
process.on("unhandledRejection", (reason) => {
  logger.error("Unhandled rejection:", reason);
});
