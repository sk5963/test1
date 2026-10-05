// Electron 창과 실제 Python IPC 연결 검증.
const { _electron: electron } = require(
  process.env.ATLAS_PLAYWRIGHT_PATH ||
    "../CODE_UI/node_modules/playwright-core",
);
const path = require("node:path");
const assert = require("node:assert/strict");
(async () => {
  const root = path.resolve(__dirname, "..");
  const { execFileSync } = require("node:child_process");
  for (const command of ["demo", "run"])
    execFileSync(process.env.ATLAS_PYTHON || "python3", ["-m", "CODE_Controller.cli", command], {cwd: root});
  const app = await electron.launch({
    executablePath: require("../CODE_UI/node_modules/electron"),
    args: [
      ...(process.platform === "linux" && process.getuid?.() === 0
        ? ["--no-sandbox"]
        : []),
      path.join(root, "CODE_UI"),
    ],
    timeout: 30000,
  });
  try {
    const page = await app.firstWindow();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page
      .getByRole("heading", { name: "FTP 자료 수신", exact: true })
      .waitFor();
    await page.locator("#demo-button").waitFor({ timeout: 15000 });
    assert.equal(await page.locator(".nav-item").count(), 6);
    await page.screenshot({
      path: path.join(root, "CODE_Docs/DEMO_SCREENSHOT.png"),
      fullPage: true,
    });
    await page.getByRole("tab", { name: "작업 설정" }).click();
    assert.equal(
      await page.locator('input[name="poll_seconds"]').inputValue(),
      "300",
    );
    await page.locator('[data-stage="statistics"]').click();
    await page.locator("#run-select").waitFor();
    await page.getByRole("tab", { name: "운영 로그" }).click();
    assert.ok((await page.locator(".log-entry").count()) > 0);
    const status = await page.evaluate(() => window.atlas.status());
    assert.ok(status.runs.some((r) => r.status === "완료"));
    assert.equal(errors.length, 0, errors.join("\n"));
    console.log("Electron 실제 창·Python IPC·메뉴·설정·로그 검증 통과");
  } finally {
    await app.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
