import { escape, date } from "./utilities.js";
export function history(data, stage, selected) {
  const rows = data.runs
    .map(
      (r) =>
        `<tr class="${r.id === selected ? "selected" : ""}" data-run="${escape(r.id)}"><td><span class="file-icon">▤</span><strong>${escape(r.source.split(/[\\/]/).at(-1))}</strong><small>${escape(r.id)}</small></td><td><span class="status ${r.status === "완료" ? "success" : r.status === "실패" ? "error" : "pending"}">${escape(r.status)}</span></td><td>${Object.values(data.steps[r.id] || {}).filter((s) => s.status === "성공").length} / 4</td><td>${r.cleaned ? "정리 완료" : "보관 중"}</td><td>${escape(date(r.updated))}</td><td><button class="button tiny" data-open="${escape(r.id)}">폴더 ↗</button></td></tr>`,
    )
    .join("");
  return /* HTML */ `<div class="card">
    <div class="card-heading">
      <div>
        <h2>처리 작업</h2>
        <p>
          실행 건을 선택하면 해당 자료의 다음 단계를 개별 실행할 수 있습니다.
        </p>
      </div>
      <span class="count">최근 ${data.runs.length}건</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>원본 / 실행 번호</th>
            <th>상태</th>
            <th>완료 단계</th>
            <th>중간 데이터</th>
            <th>최근 실행</th>
            <th>결과</th>
          </tr>
        </thead>
        <tbody>
          ${rows || '<tr><td colspan="6"><div class="empty"><strong>아직 실행한 작업이 없습니다.</strong><p>샘플 자료 준비 후 전체 파이프라인을 실행하세요.</p></div></td></tr>'}
        </tbody>
      </table>
    </div>
  </div>`;
}
