// 화면 레이아웃과 Python 명령 연결을 검증한다. Electron IPC 자체 시험과 구분한다.
const { chromium } = require(
  process.env.ATLAS_PLAYWRIGHT_PATH ||
    "../CODE_UI/node_modules/playwright-core",
);
const { pathToFileURL } = require("node:url");
const { execFile } = require("node:child_process");
const util = require("node:util");
const run = util.promisify(execFile);
const path = require("node:path");
const assert = require("node:assert/strict");
(async () => {
  const root = path.resolve(__dirname, "..");
  for (const command of ["demo", "run"])
    await run(process.env.ATLAS_PYTHON || "python3", ["-m", "CODE_Controller.cli", command], { cwd: root, maxBuffer: 8 * 1024 * 1024 });
  const packagedChromium = (
    await import(
      pathToFileURL(
        path.join(process.env.ATLAS_CHROMIUM_PACKAGE, "build/index.js"),
      ).href
    )
  ).default;
  const browser = await chromium.launch({
    executablePath:
      process.env.ATLAS_CHROMIUM_BINARY ||
      (await packagedChromium.executablePath()),
    args: [...packagedChromium.args, "--allow-file-access-from-files"],
    headless: true,
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1120 },
      deviceScaleFactor: 1,
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.exposeFunction("pythonBackend", async (action, payload) => {
      const args = ["-m", "CODE_Controller.cli"];
      if (action === "status") args.push("status");
      else if (action === "demo") args.push("demo");
      else if (action === "action") args.push("run", "--stage", payload.action);
      else throw new Error("화면 시험에서는 지원하지 않는 요청입니다.");
      const result = await run(process.env.ATLAS_PYTHON || "python3", args, {
        cwd: root,
        maxBuffer: 8 * 1024 * 1024,
      });
      return JSON.parse(result.stdout.trim().split("\n").at(-1));
    });
    await page.addInitScript(() => {
      window.atlas = {
        status: () => window.pythonBackend("status"),
        demo: () => window.pythonBackend("demo"),
        action: (p) => window.pythonBackend("action", p),
        onEvent: () => {},
        open: async () => true,
        pick: async () => null,
        service: async () => ({}),
        save: async (config) => {
          window.__savedConfig = config;
          return { type: "saved" };
        },
      };
    });
    await page.goto("file://" + path.join(root, "CODE_UI/index.html"));
    await page.locator("#demo-button").waitFor({ timeout: 15000 });
    assert.equal(await page.locator(".nav-item").count(), 6);
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({
      path: path.join(root, "CODE_Docs/DEMO_SCREENSHOT.png"),
      fullPage: true,
    });
    await page.getByRole("tab", { name: "작업 설정" }).click();
    assert.equal(
      await page.locator('input[name="histogram_bins"]').inputValue(),
      "20",
    );
    assert.equal(await page.locator('select[name="intermediate_format"]').inputValue(), "parquet");
    await page.locator('select[name="intermediate_format"]').selectOption("csv");
    await page.getByRole("button", { name: "설정 저장", exact: true }).click();
    await page.waitForFunction(() => window.__savedConfig?.intermediate_format === "csv");
    await page.locator('select[name="intermediate_format"]').selectOption("parquet");
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({path: path.join(root, "CODE_Docs/SETTINGS_SCREENSHOT.png"), fullPage: true});
    await page.locator('[data-stage="statistics"]').click();
    await page.locator("#run-select").waitFor();
    assert.ok((await page.locator("#run-select option").count()) > 1);
    await page.getByRole("tab", { name: "운영 로그" }).click();
    assert.ok((await page.locator(".log-entry").count()) > 0);
    await page.locator('[data-stage="download"]').click();
    await page.locator("#pipeline-button").click();
    await page.waitForFunction(
      () => !document.querySelector("#pipeline-button").disabled,
      { timeout: 15000 },
    );
    assert.equal(errors.length, 0, errors.join("\n"));
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    );
    assert.equal(overflow, false);
    await page.setViewportSize({ width: 1100, height: 900 });
    await page.screenshot({
      path: path.join(root, "CODE_Docs/DEMO_SCREENSHOT_COMPACT.png"),
      fullPage: true,
    });
    const report = await browser.newPage();
    await report.goto(
      "file://" +
        path.join(
          root,
          "workspace/runs",
          (await page.evaluate(() => window.atlas.status())).runs[0].id,
          "report/index.html",
        ),
    );
    const fs = require("node:fs");
    const fontFolder = path.join(root, "CODE_UI/fonts");
    const fontCss = fs
      .readFileSync(path.join(fontFolder, "font.css"), "utf8")
      .replace(
        /url\(\.\/files\/([^)]*)\)/g,
        (_, name) =>
          "url(data:font/woff2;base64," +
          fs
            .readFileSync(path.join(fontFolder, "files", name))
            .toString("base64") +
          ")",
      );
    await report.addStyleTag({
      content:
        fontCss + 'body { font-family: "Noto Sans KR Variable", sans-serif; }',
    });
    await report.evaluate(() => document.fonts.ready);
    assert.ok(await report.getByText("90.62%", { exact: true }).count());
    await report.screenshot({
      path: path.join(root, "CODE_Docs/REPORT_SCREENSHOT.png"),
      fullPage: true,
    });
    console.log(
      "화면 1440/1100 폭·탭·메뉴·실제 Python 상태/실행·Report 렌더링 검증 통과",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
