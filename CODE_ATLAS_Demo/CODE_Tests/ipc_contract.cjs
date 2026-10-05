// 네이티브 창 대신 Electron 경계를 대체해 실제 Python 자식 프로세스 호출을 검증한다.
const fs = require("node:fs"),
  path = require("node:path"),
  vm = require("node:vm"),
  assert = require("node:assert/strict");
const handlers = new Map();
const root = path.resolve(__dirname, "..");
const electron = {
  app: { whenReady: () => Promise.resolve(), on: () => {}, quit: () => {} },
  BrowserWindow: class {
    constructor() {
      this.webContents = {
        id: 42,
        send: () => {},
        setWindowOpenHandler: () => {},
        on: () => {},
      };
    }
    loadFile() {}
    isDestroyed() {
      return false;
    }
  },
  ipcMain: { handle: (name, handler) => handlers.set(name, handler) },
  dialog: { showOpenDialog: async () => ({ canceled: true }) },
  shell: { openPath: async () => "" },
};
(async () => {
  const { execFileSync } = require("node:child_process");
  for (const command of ["demo", "run"])
    execFileSync(process.env.ATLAS_PYTHON || "python3", ["-m", "CODE_Controller.cli", command], { cwd: root });
  const file = path.join(root, "CODE_UI/main.cjs");
  vm.runInNewContext(fs.readFileSync(file, "utf8"), {
    require: (name) => (name === "electron" ? electron : require(name)),
    __dirname: path.dirname(file),
    process,
    console,
  });
  await new Promise((resolve) => setImmediate(resolve));
  const event = { sender: { id: 42 } };
  const status = await handlers.get("engine:status")(event);
  assert.equal(status.type, "status");
  assert.ok(status.runs.some((r) => r.status === "완료"));
  const receipt = await handlers.get("engine:action")(event, {
    action: "download",
  });
  assert.equal(receipt.type, "result");
  assert.ok(receipt.result.skipped >= 1);
  await assert.rejects(
    () => handlers.get("engine:action")(event, { action: "unexpected" }),
    /지원하지/,
  );
  await assert.rejects(
    () => handlers.get("engine:status")({ sender: { id: 99 } }),
    /허용하지/,
  );
  const previous = structuredClone(status.config);
  try {
    const updated = structuredClone(previous);
    updated.intermediate_format = previous.intermediate_format === "parquet" ? "csv" : "parquet";
    assert.equal((await handlers.get("engine:save")(event, updated)).type, "saved");
    assert.equal((await handlers.get("engine:status")(event)).config.intermediate_format, updated.intermediate_format);
  } finally {
    await handlers.get("engine:save")(event, previous);
  }
  assert.equal(await handlers.get("engine:pick")(event), null);
  console.log("Electron IPC 경계 + 실제 Python 프로세스 호출 검증 통과");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
