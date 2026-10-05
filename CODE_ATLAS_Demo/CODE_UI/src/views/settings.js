import { escape } from "./utilities.js";
export function settings(data) {
  const c = data.config;
  return /* HTML */ `<form id="settings-form">
    <div class="card">
      <div class="card-heading">
        <div>
          <h2>전송 및 작업 설정</h2>
          <p>서버 자동 실행과 사용자 수동 실행이 같은 설정을 사용합니다.</p>
        </div>
        <span class="count">비밀번호는 환경변수로 관리</span>
      </div>
      <div class="form-grid">
        <label>중간 데이터 포맷<select name="intermediate_format">
          <option value="parquet" ${c.intermediate_format === "parquet" ? "selected" : ""}>Parquet · ZSTD 압축</option>
          <option value="csv" ${c.intermediate_format === "csv" ? "selected" : ""}>CSV · 기존 포맷 호환</option>
        </select></label>
        <label
          >전송 방식<select name="transport">
            <option value="demo" ${c.transport === "demo" ? "selected" : ""}>
              로컬 모의 전송
            </option>
            <option value="ftp" ${c.transport === "ftp" ? "selected" : ""}>
              실제 FTP
            </option>
          </select></label
        ><label
          >FTP 서버<input name="host" value="${escape(c.ftp.host)}" /></label
        ><label
          >FTP 포트<input
            name="port"
            type="number"
            min="1"
            max="65535"
            value="${c.ftp.port}" /></label
        ><label
          >자동 확인 간격 (초)<input
            name="poll_seconds"
            type="number"
            min="5"
            max="86400"
            value="${c.poll_seconds}" /></label
        ><label
          >FTP 원본 경로<input
            name="remote_input"
            value="${escape(c.ftp.remote_input)}" /></label
        ><label
          >FTP 결과 경로<input
            name="remote_output"
            value="${escape(c.ftp.remote_output)}" /></label
        ><label
          >중간 데이터 보관기간 (일)<input
            name="retention_days"
            type="number"
            min="0"
            max="3650"
            value="${c.retention_days}" /></label
        ><label
          >히스토그램 구간 수<input
            name="histogram_bins"
            type="number"
            min="2"
            max="200"
            value="${c.histogram_bins}" /></label
        ><label class="check"><input name="measurement_excel_enabled" type="checkbox" ${c.measurement_excel_enabled ? "checked" : ""} />전체 측정값 Excel도 생성</label>
        <label class="check"
          ><input name="tls" type="checkbox" ${c.ftp.tls ? "checked" : ""} />
          FTPS 암호화 연결</label
        ><label class="check"
          ><input
            name="cleanup_enabled"
            type="checkbox"
            ${c.cleanup_enabled ? "checked" : ""}
          />
          완료 후 보관기간이 지난 중간 데이터 자동 정리</label
        >
      </div>
      <div class="form-footer">
        <p>
          계정: ATLAS_FTP_USER / 비밀번호: ATLAS_FTP_PASSWORD<br />원본과 최종
          결과물은 정리 대상에서 제외됩니다. 실행 중 설정 변경은 다음 자동
          주기에 반영됩니다.
        </p>
        <button class="button primary" type="submit">설정 저장</button>
      </div>
    </div>
  </form>`;
}
