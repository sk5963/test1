import { escape, date } from "./utilities.js";
export function logs(data) {
  return /* HTML */ `<div class="card">
    <div class="card-heading">
      <div>
        <h2>운영 로그</h2>
        <p>단계별 진행과 오류 · 최근 100개 기록</p>
      </div>
      <span class="count">실시간 기록</span>
    </div>
    <div class="log-list">
      ${data.events.map((e) => `<div class="log-entry"><time>${escape(date(e.created))}</time><span class="log-stage">${escape(e.stage)}</span><span>${escape(e.message)}</span></div>`).join("") || '<div class="empty">로그가 없습니다.</div>'}
    </div>
  </div>`;
}
