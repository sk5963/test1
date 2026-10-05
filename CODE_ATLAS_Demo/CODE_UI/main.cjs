// Electron는 명령 조정과 창만 담당한다. 데이터 처리는 Python에 위임한다.
const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const ROOT = path.resolve(__dirname, "..");
const CONFIG = path.join(ROOT, "config.json");
let window,
  manualBusy = false;
function python() {
  const local = path.join(
    ROOT,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  if (process.env.ATLAS_PYTHON) return [process.env.ATLAS_PYTHON, []];
  if (fs.existsSync(local)) return [local, []];
  return process.platform === "win32" ? ["py", ["-3"]] : ["python3", []];
}
function command(args, input) {
  return new Promise((resolve, reject) => {
    const [exe, prefix] = python();
    const child = spawn(
      exe,
      [...prefix, "-m", "CODE_Controller.cli", ...args, "--config", CONFIG],
      {
        cwd: ROOT,
        shell: false,
        windowsHide: true,
        env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      },
    );
    let buffer = "",
      messages = [],
      stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (block) => {
      buffer += block.toString("utf8");
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const event = JSON.parse(line);
          messages.push(event);
          if (messages.length > 1000) messages.shift();
          if (event.type === "progress" && window && !window.isDestroyed())
            window.webContents.send("engine:event", event);
        } catch {
          stderr = (stderr + line.slice(0, 1000)).slice(-5000);
        }
      }
    });
    child.stderr.on("data", (block) => {
      stderr = (stderr + block.toString()).slice(-5000);
    });
    child.on("error", () =>
      reject(
        new Error(
          "Python을 실행할 수 없습니다. 설치 스크립트를 먼저 실행하세요.",
        ),
      ),
    );
    child.on("close", (code) => {
      if (code !== 0)
        reject(
          new Error(
            messages.findLast((m) => m.type === "error")?.message ||
              stderr ||
              "처리에 실패했습니다. 로그를 확인하세요.",
          ),
        );
      else resolve(messages.at(-1));
    });
    child.stdin.end(input ? JSON.stringify(input) : undefined);
  });
}
function sender(event) {
  if (!window || event.sender.id !== window.webContents.id)
    throw new Error("허용하지 않은 호출입니다.");
}
function runId(value) {
  if (typeof value !== "string" || !/^[a-zA-Z0-9-]+$/.test(value))
    throw new Error("실행 ID가 올바르지 않습니다.");
  return value;
}
ipcMain.handle("engine:status", async (e) => {
  sender(e);
  return command(["status"]);
});
ipcMain.handle("engine:action", async (e, payload) => {
  sender(e);
  if (manualBusy) throw new Error("수동 작업이 실행 중입니다.");
  const allowed = [
    "pipeline",
    "download",
    "convert",
    "statistics",
    "report",
    "upload",
    "cleanup",
  ];
  const action = payload?.action;
  if (!allowed.includes(action)) throw new Error("지원하지 않는 작업입니다.");
  const args = ["run", "--stage", action];
  if (action === "convert") {
    if (typeof payload.input !== "string" || !fs.existsSync(payload.input))
      throw new Error("STDF 파일을 선택하세요.");
    args.push("--input", payload.input);
  } else if (["statistics", "report", "upload"].includes(action))
    args.push("--run-id", runId(payload.runId));
  manualBusy = true;
  try {
    return await command(args);
  } finally {
    manualBusy = false;
  }
});
ipcMain.handle("engine:demo", async (e) => {
  sender(e);
  return command(["demo"]);
});
ipcMain.handle("engine:save", async (e, config) => {
  sender(e);
  return command(["save-config"], config);
});
ipcMain.handle("engine:pick", async (e) => {
  sender(e);
  const result = await dialog.showOpenDialog(window, {
    properties: ["openFile"],
    filters: [{ name: "STDF 원본", extensions: ["stdf", "std"] }],
  });
  return result.canceled ? null : result.filePaths[0];
});
ipcMain.handle("engine:service", async (e, start) => {
  sender(e);
  if (!start) return command(["stop"]);
  const status = await command(["status"]);
  if (status.service.running)
    return { type: "started", message: "서버가 이미 실행 중입니다." };
  if (status.config_error) throw new Error(status.config_error);
  const state = path.join(ROOT, "workspace");
  fs.mkdirSync(state, { recursive: true });
  const fd = fs.openSync(path.join(state, "server.log"), "a");
  const [exe, prefix] = python();
  let child;
  try {
    child = spawn(
    exe,
    [...prefix, "-m", "CODE_Controller.cli", "watch", "--config", CONFIG],
    {
      cwd: ROOT,
      detached: true,
      windowsHide: true,
      stdio: ["ignore", fd, fd],
      shell: false,
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    },
  );
  await new Promise((resolve, reject) => {
    child.once("spawn", resolve);
    child.once("error", reject);
  });
    child.unref();
  } finally {
    fs.closeSync(fd);
  }
  return {
    type: "started",
    message: "화면 종료 후에도 자동 엔진이 동작합니다.",
  };
});
ipcMain.handle("engine:open", async (e, id) => {
  sender(e);
  const target = path.join(ROOT, "workspace", "runs", runId(id));
  if (!fs.existsSync(target)) throw new Error("결과 폴더가 아직 없습니다.");
  const error = await shell.openPath(target);
  if (error) throw new Error(error);
  return true;
});
app.whenReady().then(() => {
  window = new BrowserWindow({
    width: 1440,
    height: 940,
    minWidth: 1050,
    minHeight: 720,
    backgroundColor: "#f5f7fb",
    title: "ATLAS 파이프라인 자동화",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event) => event.preventDefault());
  window.loadFile(path.join(__dirname, "index.html"));
});
app.on("window-all-closed", () => app.quit());
