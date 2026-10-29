/**
 * 换装验收台 · 桌面外壳
 *
 * 做的事：拉起本地服务（必要时连带 ComfyUI）→ 打开窗口 → 关闭时收尾。
 * 不做的事：不碰生成逻辑、不碰质检。界面和浏览器里打开的是同一份页面。
 *
 * 两个刻意的选择：
 * 1. userData 放在项目目录里，不写 %APPDATA%——整个应用可以整个文件夹搬走。
 * 2. 已经在跑的服务不再起第二个，退出时也不杀别人的进程。
 */
const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');
const path = require('path');

/**
 * 有些人（包括某些 CI / 编辑器 / 抓包工具）会在环境里留一个 ELECTRON_RUN_AS_NODE=1，
 * 这会让 Electron 以"普通 Node"启动，于是 require('electron') 只返回一个可执行文件路径，
 * 后面解构出来的 app 全是 undefined，报一个毫无线索的错。
 * 这里检测到就直接以 Electron 方式重启自己一次。
 */
if (process.versions.electron && process.env.ELECTRON_RUN_AS_NODE) {
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;
  const appRoot = path.join(__dirname, '..');
  console.log('[bootstrap] 检测到 ELECTRON_RUN_AS_NODE，以 Electron 方式重启');
  const child = spawn(process.execPath, [appRoot, ...process.argv.slice(2)], {
    env,
    stdio: 'inherit',
  });
  child.on('exit', (code) => process.exit(code === null ? 0 : code));
  return;
}

const { app, BrowserWindow, shell, dialog } = require('electron');

const ROOT = path.join(__dirname, '..');
const CONFIG_PATH = path.join(ROOT, 'config.json');
const LOG_DIR = path.join(ROOT, 'logs');

const SMOKE = process.argv.includes('--smoke');

let cfg = {};
try {
  cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
} catch (e) {
  console.error('读不到 config.json：', e.message);
}

const desktop = cfg.desktop || {};
const PORT = (cfg.server && cfg.server.port) || 8770;
const COMFY_PORT = 8188;
const PYTHON = process.env.SWAP_PYTHON || desktop.python || 'python';
const URL = `http://127.0.0.1:${PORT}`;

const children = [];

app.setPath('userData', path.join(ROOT, '.electron-data'));
app.commandLine.appendSwitch('disable-features', 'HardwareMediaKeyHandling');

// ---------------------------------------------------------------- 工具

function portOpen(port, timeout = 700) {
  return new Promise((resolve) => {
    const sock = net.connect({ host: '127.0.0.1', port });
    const done = (ok) => { sock.destroy(); resolve(ok); };
    sock.setTimeout(timeout);
    sock.once('connect', () => done(true));
    sock.once('timeout', () => done(false));
    sock.once('error', () => done(false));
  });
}

async function waitPort(port, ms) {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    if (await portOpen(port)) return true;
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

function logTo(name) {
  fs.mkdirSync(LOG_DIR, { recursive: true });
  return fs.createWriteStream(path.join(LOG_DIR, name), { flags: 'w' });
}

function spawnLogged(label, cmd, args, cwd, logName) {
  const out = logTo(logName);
  const p = spawn(cmd, args, { cwd, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  p.stdout.pipe(out);
  p.stderr.pipe(out);
  p.on('error', (e) => out.write(`\n[${label}] 启动失败：${e.message}\n`));
  children.push({ label, proc: p });
  return p;
}

// ---------------------------------------------------------------- 启动顺序

async function ensureComfy() {
  if (await portOpen(COMFY_PORT)) return true;
  if (desktop.start_comfyui === false) return false;

  const dir = desktop.comfyui_dir;
  if (!dir) return false;

  spawnLogged('comfyui', PYTHON,
    ['-s', path.join(dir, 'ComfyUI', 'main.py'),
     '--windows-standalone-build', '--port', String(COMFY_PORT)],
    dir, 'comfyui.log');
  return waitPort(COMFY_PORT, 120000);
}

async function ensureServer() {
  if (await portOpen(PORT)) return { ok: true, spawned: false };

  spawnLogged('server', PYTHON, ['run.py'], ROOT, 'server.log');
  const ok = await waitPort(PORT, 60000);
  return { ok, spawned: true };
}

// ---------------------------------------------------------------- 窗口

function createWindow() {
  const win = new BrowserWindow({
    width: 1420,
    height: 940,
    minWidth: 980,
    minHeight: 640,
    backgroundColor: '#E7E6E2',
    title: '换装验收台',
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      spellcheck: false,
    },
  });

  win.once('ready-to-show', () => win.show());

  // 外链一律交给系统浏览器，别在应用窗口里打开
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith(URL)) shell.openExternal(url);
    return { action: 'deny' };
  });

  win.loadURL(URL);
  return win;
}

// ---------------------------------------------------------------- 冒烟

async function runSmoke(win) {
  try {
    const title = await win.webContents.executeJavaScript('document.title');
    const hint = await win.webContents.executeJavaScript(
      "document.getElementById('hint') ? document.getElementById('hint').textContent : ''");
    const btn = await win.webContents.executeJavaScript(
      "document.getElementById('run') ? document.getElementById('run').textContent : ''");
    const tag = await win.webContents.executeJavaScript(
      "document.getElementById('judge-tag') ? document.getElementById('judge-tag').textContent : ''");

    const img = await win.webContents.capturePage();
    const out = path.join(ROOT, 'outputs', 'electron-window.png');
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, img.toPNG());

    console.log(JSON.stringify({ title, hint, button: btn, judgeTag: tag, shot: out }, null, 2));
  } catch (e) {
    console.error('冒烟失败：', e.message);
    process.exitCode = 1;
  } finally {
    app.quit();
  }
}

// ---------------------------------------------------------------- 生命周期

app.whenReady().then(async () => {
  console.log('[main] ready, smoke =', SMOKE, '| python =', PYTHON);
  const comfyOk = await ensureComfy();
  console.log('[main] comfyui', COMFY_PORT, comfyOk ? 'up' : 'down');
  const srv = await ensureServer();
  console.log('[main] server', PORT, srv.ok ? 'up' : 'down', srv.spawned ? '(spawned)' : '(已有)');

  if (!srv.ok) {
    dialog.showErrorBox('服务起不来',
      `本地服务没有在 ${PORT} 端口就绪。\n看 logs/server.log。\n\n当前 python：${PYTHON}`);
    app.quit();
    return;
  }

  const win = createWindow();

  if (SMOKE) {
    win.webContents.once('did-finish-load', () => {
      setTimeout(() => runSmoke(win), 1500);
    });
  }

  if (!comfyOk) {
    console.warn('ComfyUI 没起来（8188）。界面能开，但点开始换会报错。');
  }
});

app.on('window-all-closed', () => {
  for (const { proc } of children) {
    if (!proc.killed) {
      try { proc.kill(); } catch (_) { /* 已经退了就算了 */ }
    }
  }
  app.quit();
});
