import { escape } from "./utilities.js";
import { history } from "./history.js";
import { pipelineStages } from "../domain/stages.js";
export function execution(data, stage, selected, input, busy, progress) {
  const complete = data.runs.filter((r) => r.status === "완료").length;
  const failed = data.runs.filter((r) => r.status === "실패").length;
  const row = data.runs.find((r) => r.id === selected);
  const steps = data.steps[selected] || {};
  const flow = pipelineStages
    .map(
      (s, i) =>
        `<div class="flow-step ${steps[s.id]?.status === "성공" ? "done" : steps[s.id]?.status === "실패" ? "failed" : ""}"><span>${steps[s.id]?.status === "성공" ? "✓" : s.tag}</span><strong>${s.label}</strong><small>${s.id === "download" && row ? "수신/입력 확보" : escape(steps[s.id]?.status || "대기")}</small></div>`,
    )
    .join("");
  const picker =
    stage.id === "convert"
      ? `<div class="input-row"><span class="label">입력 STDF</span><span class="file-path">${escape(input || "변환할 원본 파일을 선택하세요.")}</span><button class="button" id="pick-button">파일 선택</button></div>`
      : ["statistics", "report", "upload"].includes(stage.id)
        ? `<div class="input-row"><span class="label">실행 건</span><select id="run-select"><option value="">실행 이력 선택</option>${data.runs.map((r) => `<option value="${escape(r.id)}" ${r.id === selected ? "selected" : ""}>${escape(r.source.split(/[\\/]/).at(-1))} · ${escape(r.id)}</option>`).join("")}</select></div>`
        : `<div class="route"><div><small>입력</small><strong>${escape(stage.input)}</strong><span>${stage.id === "download" ? escape(data.config.ftp.remote_input) : "완료된 실행 기록 기준"}</span></div><span class="route-arrow">→</span><div><small>출력</small><strong>${escape(stage.output)}</strong><span>${stage.id === "download" ? "workspace / raw" : stage.id === "history" ? "원본 · 최종 결과 보존" : "실행별 결과 폴더"}</span></div></div>`;
  return /* HTML */ `<div class="intro">
      <div>
        <span class="eyebrow">처리 단계 ${stage.tag}</span>
        <h2>
          ${stage.id === "download" ? "새 자료를 받고, 반복 작업을 줄이세요." : escape(stage.label)}
        </h2>
        <p>${escape(stage.caption)}</p>
      </div>
      <button class="button" id="demo-button">
        샘플 자료 준비 <span>＋</span>
      </button>
    </div>
    <div class="metrics">
      <div>
        <span>전체 실행 건</span
        ><strong>${data.runs.length}<small>건</small></strong>
      </div>
      <div>
        <span>처리 완료</span><strong>${complete}<small>건</small></strong
        ><i class="metric-dot green"></i>
      </div>
      <div>
        <span>확인할 오류</span><strong>${failed}<small>건</small></strong
        ><i class="metric-dot orange"></i>
      </div>
      <div>
        <span>자동 확인 간격</span
        ><strong>${data.config.poll_seconds}<small>초</small></strong>
      </div>
    </div>
    <div class="card">
      <div class="card-heading">
        <div>
          <h2>파이프라인 현황</h2>
          <p>${row ? escape(row.id) : "실행 건별로 단계 상태를 연결합니다."}</p>
        </div>
        <span class="status ${data.busy ? "pending" : "success"}"
          >${data.busy ? "작업 실행 중" : "실행 가능"}</span
        >
      </div>
      <div class="flow">${flow}</div>
    </div>
    <div class="card action-card">
      <div class="card-heading">
        <div>
          <h2>${escape(stage.label)} 제어</h2>
          <p>단계 단독 실행 또는 전체 자동 처리</p>
        </div>
        <span class="count"
          >${data.config.transport === "demo" ? "모의 전송 모드" : "FTP 전송 모드"}</span
        >
      </div>
      ${picker}
      <div class="action-footer">
        <div class="progress-info">
          <span id="progress-text"
            >${escape(progress?.message || "작업을 시작할 준비가 되었습니다.")}</span
          >
          <div class="progress-track">
            <div
              id="progress-bar"
              style="width:${progress?.percent || 0}%"
            ></div>
          </div>
        </div>
        <button
          class="button primary"
          id="stage-button"
          ${busy ? "disabled" : ""}
        >
          ${escape(stage.action)} <span>→</span>
        </button>
      </div>
    </div>
    <div class="server-banner">
      <div class="server-icon">◈</div>
      <div>
        <strong>서버 상시 실행</strong>
        <p>
          자동 엔진은 화면을 닫아도 계속 동작합니다. 중지는 현재 작업 완료 후
          적용됩니다.
        </p>
      </div>
      <button class="button" id="service-button">
        ${data.service.running ? "자동 실행 중지" : "자동 실행 시작"}
      </button>
    </div>
    ${history(data, stage, selected)}`;
}
