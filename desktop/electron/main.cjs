'use strict';
const {app, BrowserWindow, Menu, dialog, shell} = require('electron');
const {spawn} = require('node:child_process');
const {randomBytes} = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const {isLocalOrigin, isBackendOrigin, injectToken} = require('./policy.cjs');
const smoke = process.argv.includes('--smoke-test');
app.setName('English Match');
app.setPath('userData', smoke && process.env.EM_SMOKE_DATA ? process.env.EM_SMOKE_DATA : path.join(app.getPath('appData'), 'English Match'));
if (smoke) app.disableHardwareAcceleration();
const profileDir = app.getPath('userData');
const dataDir = path.join(profileDir, 'data');
const token = randomBytes(32).toString('hex');
let win, backend, origin = '', quitting = false, quittingPromise, ready = false;
const timeout = (promise, ms, message) => {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => {timer = setTimeout(() => reject(new Error(message)), ms);})]).finally(() => clearTimeout(timer));
};
function log(text) {
  fs.mkdirSync(profileDir, {recursive:true});
  const file = path.join(profileDir, 'desktop.log');
  try {
    if (fs.existsSync(file) && fs.statSync(file).size > 1024 * 1024) fs.writeFileSync(file, '');
    fs.appendFileSync(file, new Date().toISOString() + ' ' + String(text).split(token).join('[redacted]') + '\n');
  } catch {}
}
function startBackend() {
  const frozen = app.isPackaged || process.env.EM_USE_FROZEN_BACKEND === '1';
  const executable = process.platform === 'win32' ? 'english-match-backend.exe' : 'english-match-backend';
  const folder = app.isPackaged ? path.join(process.resourcesPath, 'backend') : path.join(__dirname, '..', 'build', 'backend', 'english-match-backend');
  const command = frozen ? path.join(folder, executable) : (process.env.EM_PYTHON || (process.platform === 'win32' ? 'python' : 'python3'));
  const args = frozen ? [] : [path.join(__dirname, '..', 'backend', 'desktop_server.py')];
  args.push('--data-dir', dataDir);
  const environment = {...process.env, PYTHONUNBUFFERED:'1', PYTHONIOENCODING:'utf-8', ENGLISH_MATCH_DESKTOP_TOKEN:token};
  delete environment.PYTHONHOME;
  delete environment.PYTHONPATH;
  backend = spawn(command, args, {env:environment, stdio:['pipe','pipe','pipe'], windowsHide:true});
  backend.stderr.on('data', data => log(data.toString()));
  backend.stdin.on('error', () => {});
  return timeout(new Promise((resolve, reject) => {
    const lines = readline.createInterface({input:backend.stdout});
    lines.on('line', line => {
      try {
        const event = JSON.parse(line);
        if (event.event === 'ready' && isBackendOrigin(event.origin)) resolve(event.origin);
      } catch { log(line); }
    });
    backend.on('error', reject);
    backend.once('exit', (code) => {
      if (!quitting && ready) {
        ready = false;
        if (!smoke) dialog.showErrorBox('English Match đã dừng', 'Hãy mở lại ứng dụng. Dữ liệu đã lưu vẫn nằm trên máy. Chi tiết: ' + path.join(profileDir, 'desktop.log'));
        app.quit();
      }
      reject(new Error('Máy chủ trên máy đã dừng (mã ' + code + ').'));
    });
  }), 60000, 'Khởi động quá lâu. Hãy mở lại ứng dụng.');
}
async function stopBackend() {
  if (!backend || backend.exitCode !== null || backend.signalCode !== null) return;
  await new Promise(resolve => {
    const timer = setTimeout(() => { backend.kill(); resolve(); }, 8000);
    backend.once('exit', () => {clearTimeout(timer); resolve();});
    backend.stdin.end();
  });
}
function quit() {
  if (quittingPromise) return quittingPromise;
  quittingPromise = (async () => {
    try {
      if (ready && win && !win.isDestroyed()) await timeout(win.webContents.executeJavaScript('window.EnglishMatchDesktop?.flush()'), 7000, 'Chưa lưu xong tiến độ.');
    } catch (error) {
      if (!smoke) {
        const result = await dialog.showMessageBox(win, {type:'warning', buttons:['Quay lại để lưu', 'Thoát ứng dụng'], defaultId:0, cancelId:0, message:'Tiến độ mới nhất chưa được lưu.', detail:'Bạn có thể quay lại và bấm Thử lưu lại. Nếu thoát ngay, những thay đổi chưa lưu có thể bị mất.'});
        if (result.response === 0) return;
      }
    }
    quitting = true;
    await stopBackend();
    app.quit();
  })().finally(() => {quittingPromise = null;});
  return quittingPromise;
}
function buildMenu() {
  const dataTab = () => win?.webContents.executeJavaScript(`document.querySelector('[data-view="data"]')?.click()`).catch(log);
  const template = [
    {label:'English Match', submenu:[
      {label:'Về English Match', click:() => dialog.showMessageBox(win, {type:'info', message:'English Match ' + app.getVersion(), detail:'Ứng dụng học từ vựng offline, chuyển từ file web bạn cung cấp.\nDữ liệu được lưu riêng trên máy này.\nChọn Nhập & sao lưu để chuyển dữ liệu sang máy khác.'})},
      {type:'separator'}, {label:'Thoát', accelerator:'CmdOrCtrl+Q', click:quit}
    ]},
    {label:'Chỉnh sửa', submenu:[{role:'undo', label:'Hoàn tác'}, {role:'redo', label:'Làm lại'}, {type:'separator'}, {role:'cut', label:'Cắt'}, {role:'copy', label:'Sao chép'}, {role:'paste', label:'Dán'}, {role:'selectAll', label:'Chọn tất cả'}]},
    {label:'Hiển thị', submenu:[{role:'reload', label:'Tải lại giao diện'}, {role:'resetZoom', label:'Kích thước gốc'}, {role:'zoomIn', label:'Phóng to'}, {role:'zoomOut', label:'Thu nhỏ'}, {role:'togglefullscreen', label:'Toàn màn hình'}]},
    {label:'Dữ liệu', submenu:[{label:'Nhập & sao lưu…', click:dataTab}, {label:'Mở thư mục dữ liệu', click:() => shell.openPath(dataDir).then(error => {if(error) log(error);})}]},
    {label:'Trợ giúp', submenu:[{label:'Cách sử dụng', click:() => dialog.showMessageBox(win, {type:'info', message:'Học từ vựng trên máy', detail:'1. Mở Học từ để ghép từ tiếng Anh và nghĩa.\n2. Quản lý từ & list để thêm hoặc sửa từ.\n3. Nhập & sao lưu để nhập CSV hoặc xuất JSON.\nỨng dụng tự lưu tiến độ. Bạn có thể tắt mạng khi học.\nTrước khi chuyển máy, xuất bản sao lưu JSON rồi khôi phục trên máy mới.'})}]}
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}
async function createWindow() {
  let bounds = {width:1240,height:850};
  try {
    const saved = JSON.parse(fs.readFileSync(path.join(profileDir, 'window.json'), 'utf8'));
    if (Number.isInteger(saved.width) && Number.isInteger(saved.height)) bounds = {width:Math.min(1920,Math.max(820,saved.width)),height:Math.min(1200,Math.max(620,saved.height))};
  } catch {}
  win = new BrowserWindow({...bounds, minWidth:820, minHeight:620, show:!smoke, backgroundColor:'#f6f7fb', title:'English Match', icon:path.join(__dirname, 'icon.png'), webPreferences:{nodeIntegration:false, contextIsolation:true, sandbox:true, webSecurity:true, allowRunningInsecureContent:false, spellcheck:false, partition:'persist:english-match'}});
  const wc = win.webContents, session = wc.session;
  session.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  session.setPermissionCheckHandler(() => false);
  session.webRequest.onBeforeSendHeaders({urls:['http://*/*','https://*/*']}, (details, callback) => callback({requestHeaders:injectToken(details.requestHeaders,details.url,origin,token)}));
  session.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*','ws://*/*','wss://*/*']}, (details, callback) => callback({cancel:!isLocalOrigin(details.url,origin)}));
  wc.setWindowOpenHandler(() => ({action:'deny'}));
  wc.on('will-attach-webview', event => event.preventDefault());
  wc.on('will-navigate', (event, url) => {if (!isLocalOrigin(url,origin)) event.preventDefault();});
  wc.on('will-redirect', (event, url) => {if (!isLocalOrigin(url,origin)) event.preventDefault();});
  wc.on('will-prevent-unload', () => { if (!smoke) dialog.showMessageBox(win, {type:'info', message:'Đang lưu tiến độ', detail:'Hãy đợi dòng Đã lưu tiến độ rồi thử lại.'}); });
  session.on('will-download', (_event, item) => item.setSaveDialogOptions({defaultPath:path.join(app.getPath('downloads'),path.basename(item.getFilename())), title:'Lưu bản sao English Match'}));
  win.on('close', event => {
    if (!quitting) {event.preventDefault(); quit();}
  });
  win.on('resize', () => {if (!win.isMaximized() && !win.isFullScreen()) {try {fs.writeFileSync(path.join(profileDir,'window.json'),JSON.stringify(win.getBounds()));} catch {}}});
  await wc.loadFile(path.join(__dirname, 'loading.html'));
  buildMenu();
  origin = await startBackend();
  await wc.loadURL(origin);
  ready = true;
  if (smoke) {
    try {
      await require('./smoke.cjs').run({win,origin,token,dataDir,quit});
    } catch (error) {
      log(error.stack); console.error(error); quitting=true; await stopBackend(); app.exit(1);
    }
  }
}
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if(win){if(win.isMinimized())win.restore();win.show();win.focus();} });
  app.on('before-quit', event => {if (!quitting){event.preventDefault();quit();}});
  app.whenReady().then(createWindow).catch(async error => {
    log(error.stack); if (!smoke) dialog.showErrorBox('Không mở được English Match', error.message + '\nChi tiết: ' + path.join(profileDir,'desktop.log'));
    quitting=true;await stopBackend();app.exit(1);
  });
}
