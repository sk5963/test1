# 구성요소와 변경 위치

## 원칙

- 구성요소 폴더는 CODE_xxxx로 명명한다. 내부 Python 패키지, 글꼴 및 실행 데이터 폴더는 기술적 이름을 유지한다.
- UI, 작업 조정, 각 처리 기능, 데이터 계약을 분리한다.
- 결과물 생성 로직을 Electron에 넣지 않는다.
- 기능 수정 시 해당 구성요소와 계약 검증만 먼저 읽는다. 전체 소스를 반복해서 읽지 않는다.
- 사용 가능한 기존 변환 로직은 CODE_Vendor에 보존한다. 해시 검증 없이 수정하지 않는다.
- 설정·입력·출력 형식이 바뀌면 schema_version과 관련 검증을 함께 확인한다.
- 기능 추가 시 실제 사용자 화면과 실행 경계를 함께 확인한다. 동일 로직을 서버용·수동용으로 복제하지 않는다.

## 기능별 수정 지점

| 기능 | 주된 파일 | 연결 계약 |
| --- | --- | --- |
| FTP 수신·업로드 | CODE_FTP/service.py | receive / publish |
| STDF 변환 연결 | CODE_STDF_Converter/service.py | source + 새 output → conversion.json |
| 원본 바이너리 변환기 | CODE_Vendor/ate_parsers/stdf/binary_parser.py | 기존 Full CSV 포맷 |
| 기존 CSV 해석 | CODE_Common/full_csv.py | 행 유형 0.2~0.9, 1, 완료 마커 |
| 측정 데이터 읽기·Parquet 기록 | CODE_Common/measurements.py | 가로형 CSV / Parquet 공통 읽기 |
| 단계 결과 무결성 | CODE_Common/artifacts.py | 단계 파일 목록·크기·해시 |
| 통계 계산 | CODE_Statistics/service.py | Parquet / CSV → summary·histograms·map |
| 차트·맵 출력 | CODE_Statistics/charts.py, templates/histograms.html | 히스토그램 HTML·맵 SVG |
| 전체 측정값 Excel | CODE_Statistics/measurement_workbook.py | 배치 읽기 → 행 제한에 따른 분할 시트 |
| 통계시트 출력 | CODE_Statistics/workbook.py | 고정 Excel 포맷 |
| Report 조정 | CODE_Report/service.py | conversion + statistics → report |
| Report 디자인 | CODE_Report/templates/report.html | 출력 페이지 템플릿 |
| 단계 순서·선행 검사 | CODE_Controller/pipeline.py | 수신 → 변환 → 통계 → Report → 업로드 |
| 자동 반복·명령 경계 | CODE_Controller/cli.py | JSON Lines, watch / stop |
| 중간 데이터 정리 | CODE_Controller/cleanup.py | 완료·기간·해시 확인 |
| 이력 DB | CODE_Common/store.py | runs / steps / receipts / publications / events |
| 설정·해시·잠금 | CODE_Common/io.py | config.json, file_lock, write_json |
| Electron 프로세스 연결 | CODE_UI/main.cjs, preload.cjs | 허용된 IPC 명령만 공개 |
| 메뉴·탭 정의 | CODE_UI/src/domain/stages.js | 단계 식별자와 설명 |
| UI 상태·동작 연결 | CODE_UI/src/app.js | IPC 상태·사용자 선택 |
| UI 본문 | CODE_UI/src/views/execution.js, settings.js, history.js, logs.js | 기능별 화면 |
| 공통 화면 디자인 | CODE_UI/style.css | 좌측 메뉴 / 우측 상단 탭 / 본문 |
| 합성 STDF | CODE_Demo_Data/generate.py | 고정 난수값의 샘플 |

## 실행·자료 식별

수신 이력은 전송 방식·서버·포트·암호화 여부·원격 경로·로컬 저장 위치로 구분한다. 처리 실행은 원본 경로·SHA-256·처리 도구 버전·출력 포맷·통계 설정·전송 설정으로 구분한다. 자동 확인 간격이나 보관기간 변경만으로 동일 자료를 재변환하지 않는다. 각 실행의 설정을 저장하고 후속 단계에서도 해당 설정을 사용한다.

각 실행 폴더는 고유 실행 번호로 구분한다. 성공 단계는 재실행 시 덮어쓰지 않는다. 같은 중간 데이터가 정리된 뒤에는 원본으로 새 변환 실행을 만든다. 테스트 번호는 단독 고유키로 취급하지 않고 프로그램 정보 및 열 위치와 함께 구분한다. 중복된 테스트 번호도 열별로 통계를 생성한다. 성공 결과는 저장한 파일 목록·해시로 검증한다. 손상 결과를 자동 처리할 때는 새 실행 건을 만들어 기존 실행 결과를 보존한다.

## 데이터·명령 계약

- conversion.json: schema_version 2, source_sha256, data_path, data_sha256, data_bytes, data_format, compression, metadata, rows, items. CSV 호환 모드는 full_csv를 채우고 Parquet 모드는 null이다. csv_sha256/csv_bytes는 원본 엔진 연결 CSV의 생성 기록으로 유지한다.
- summary.json: schema_version 2, data_sha256, data_format, csv_sha256(CSV 입력만), total, passed, failed, yield_percent, test_count, 수율·맵 정책.
- histograms.json: 테스트 열별 식별자·원본 번호·이름·단위·리밋·통계·구간·빈도.
- map.json: 측정 행·좌표·판정·사이트·SBIN. 동일 좌표의 여러 측정 행은 데이터에 유지한다.
- report.json: 입력 중간 데이터·원본·Report 해시 및 data_format.
- complete.json: run_id와 최종 결과 파일의 상대 경로·크기·해시. Parquet/CSV는 포함하지 않는다.
- Controller stdout: 한 줄에 JSON 한 개. type은 progress / result / error / status 등이다. progress에는 stage, message, percent, run_id, time이 있다.
- 실패 종료 코드: 1. 실행 중단: 130. 성공: 0. 실패 자료는 완료 이력으로 기록하지 않는다.

## 후속 변경 후보

통계 계산, 차트·맵 렌더링, Excel 렌더링은 CODE_Statistics 내부에서 파일별로 분리했다. Report 디자인도 외부 HTML 템플릿으로 분리했다. 원본 파서의 판정 및 단위 처리를 별도 통계 프로그램에서 재해석하지 않는다.

별도 결과물 뷰어, 중앙 다중 PC 작업 API, 로컬 보관 루트 선택, 압축 STDF 입력, 최초/최종 시험 수율, 업로드 후 원격 검증, OS 서비스 등록과 로그 회전은 후속 구현 항목이다.

Parquet 자체 데이터 계약은 wide_measurements_v1이다. 열·메타데이터 키는 DATA_FORMAT.md에 명시했다. 기존 JSON 스키마 1의 CSV 기록 읽기는 호환 경로를 유지한다.
