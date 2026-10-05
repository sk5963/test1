import { stages, tabs } from "./domain/stages.js";
import { execution, settings, history, logs } from "./views/render.js";
const api = window.atlas;
let data = null,
  stage = stages[0],
  tab = "run",
  selected = "",
  input = "",
  busy = false,
  progress = null;
const $ = (id) => document.getElementById(id);
function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.add("visible");
  setTimeout(() => $("toast").classList.remove("visible"), 5000);
}
async function refresh(force = false) {
  if (!api) {
    $("content").innerHTML =
      '<div class="card empty">Electron 실행 환경에서 열어 주세요. 설치 후 npm start로 실행할 수 있습니다.</div>';
    return;
  }
  try {
    data = await api.status();
    if (data.config_error) toast("설정 오류: " + data.config_error + " 작업 설정에서 다시 저장하세요.");
    if (!selected && data.runs.length) selected = data.runs[0].id;
    if (force || tab !== "settings") render();
  } catch (e) {
    toast(e.message);
    if (!data)
      $("content").innerHTML =
        '<div class="card empty">엔진 연결을 확인하세요. Python 의존성 설치가 필요합니다.</div>';
  }
}
function render() {
  $("navigation").innerHTML = stages
    .map(
      (s) =>
        `<button class="nav-item ${stage.id === s.id ? "active" : ""}" data-stage="${s.id}"><span class="nav-icon">${s.icon}</span>${s.label}<small>${s.tag}</small></button>`,
    )
    .join("");
  document.querySelectorAll("[data-stage]").forEach(
    (b) =>
      (b.onclick = () => {
        stage = stages.find((s) => s.id === b.dataset.stage);
        tab = "run";
        render();
      }),
  );
  $("page-title").textContent = stage.label;
  $("breadcrumb-stage").textContent = stage.label;
  $("transport-label").textContent =
    data.config.transport === "demo" ? "모의 전송 · 데모" : "FTP 연결";
  $("engine-label").textContent = data.service.running
    ? "자동 엔진 실행 중"
    : "수동 실행 대기";
  $("engine-dot").classList.toggle("running", data.service.running);
  $("tabs").innerHTML = tabs
    .map(
      (t) =>
        `<button role="tab" aria-selected="${tab === t.id}" class="tab ${tab === t.id ? "active" : ""}" data-tab="${t.id}">${t.label}</button>`,
    )
    .join("");
  document.querySelectorAll("[data-tab]").forEach(
    (b) =>
      (b.onclick = () => {
        tab = b.dataset.tab;
        render();
      }),
  );
  $("content").innerHTML =
    tab === "settings"
      ? settings(data)
      : tab === "logs"
        ? logs(data)
        : tab === "history"
          ? history(data, stage, selected)
          : execution(data, stage, selected, input, busy, progress);
  bind();
  $("pipeline-button").disabled = busy || Boolean(data.config_error);
}
async function perform(action) {
  if (busy) return;
  busy = true;
  if (data) render();
  try {
    const result = await action();
    toast(result?.message || "요청을 처리했습니다.");
    if (result?.result?.run_id) selected = result.result.run_id;
  } catch (e) {
    toast(e.message);
  } finally {
    busy = false;
    await refresh(true);
  }
}
function bind() {
  document.querySelectorAll("[data-run]").forEach(
    (row) =>
      (row.onclick = () => {
        selected = row.dataset.run;
        render();
      }),
  );
  document.querySelectorAll("[data-open]").forEach(
    (button) =>
      (button.onclick = (e) => {
        e.stopPropagation();
        perform(() => api.open(button.dataset.open));
      }),
  );
  if ($("pick-button"))
    $("pick-button").onclick = async () => {
      const file = await api.pick();
      if (file) {
        input = file;
        render();
      }
    };
  if ($("run-select"))
    $("run-select").onchange = (e) => {
      selected = e.target.value;
      render();
    };
  if ($("demo-button"))
    $("demo-button").onclick = () => perform(() => api.demo());
  if ($("stage-button"))
    $("stage-button").onclick = () =>
      perform(() =>
        api.action({
          action: stage.id === "history" ? "cleanup" : stage.id,
          input,
          runId: selected,
        }),
      );
  if ($("service-button"))
    $("service-button").onclick = () =>
      perform(() => api.service(!data.service.running));
  if ($("settings-form"))
    $("settings-form").onsubmit = (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      const config = structuredClone(data.config);
      for (const k of ["poll_seconds", "retention_days", "histogram_bins"])
        config[k] = Number(f.get(k));
      config.transport = f.get("transport");
      config.intermediate_format = f.get("intermediate_format");
      config.cleanup_enabled = f.has("cleanup_enabled");
      config.measurement_excel_enabled = f.has("measurement_excel_enabled");
      for (const k of ["host", "remote_input", "remote_output"])
        config.ftp[k] = f.get(k);
      config.ftp.port = Number(f.get("port"));
      config.ftp.tls = f.has("tls");
      perform(() => api.save(config));
    };
}
$("refresh-button").onclick = () => refresh(true);
$("pipeline-button").onclick = () =>
  perform(() => api.action({ action: "pipeline" }));
api?.onEvent((event) => {
  progress = event;
  if ($("progress-text")) $("progress-text").textContent = event.message;
  if ($("progress-bar"))
    $("progress-bar").style.width =
      Math.max(0, Math.min(100, event.percent || 0)) + "%";
});
refresh(true);
setInterval(() => {
  if (!busy) refresh();
}, 5000);
