const fs = require("node:fs"),
  path = require("node:path"),
  { spawnSync } = require("node:child_process");
function files(folder) {
  return fs
    .readdirSync(folder, { withFileTypes: true })
    .flatMap((entry) =>
      entry.isDirectory()
        ? files(path.join(folder, entry.name))
        : [path.join(folder, entry.name)],
    );
}
const root = path.resolve(__dirname, "..");
for (const file of [
  path.join(root, "main.cjs"),
  path.join(root, "preload.cjs"),
  ...files(path.join(root, "src")),
]) {
  const result = spawnSync(process.execPath, ["--check", file], {
    stdio: "inherit",
  });
  if (result.status !== 0) process.exit(1);
}
console.log("Electron 및 화면 JavaScript 구문 검증 통과");
