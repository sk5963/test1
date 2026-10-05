# ATLAS 파이프라인 자동화 데모 0.2.1

서버 PC 상시 실행과 사용자 PC 수동 실행이 같은 Python 처리 엔진을 사용하는 데모입니다. Electron은 설정·실행·운영 이력을 담당하며, 통계 결과와 Report는 독립 파일로 생성합니다. 결과물 조회·편집용 별도 프로그램은 이 패키지의 구현 범위 밖입니다.

기존 STDF.zip의 바이너리 변환 엔진을 수정 없이 포함했습니다. 가로형 측정 데이터를 기본 Parquet · ZSTD로 출력하고 기존 Full CSV 선택도 지원하며, 원본 변환 로직의 동작 범위와 경고도 이어받습니다. 원본 출처와 파일별 해시는 CODE_Vendor/SOURCE_MANIFEST.json에 있습니다.

## 설치 전 샘플 확인

`CODE_Demo_Data/example_results/report/index.html`을 브라우저로 열면 샘플 Report와 통계 결과를 볼 수 있습니다. 샘플 STDF는 `CODE_Demo_Data/samples`에 있습니다. 예시의 conversion.json 경로는 설명용이며 실행 입력으로 사용하지 않습니다.

## 빠른 시작 — Windows

필요 환경: Python 3.10 이상, Node.js 22 이상. 설치 단계에서는 인터넷 접속이 필요합니다. 이 패키지는 설치형 EXE가 아닌 실행 가능한 소스 데모입니다.

1. ZIP을 압축 해제합니다. 폴더명과 내부 구조를 유지하세요.
2. `setup_windows.bat`를 실행해 Python 가상환경과 Electron을 설치합니다.
3. `start_ui_windows.bat`를 실행합니다. 합성 STDF 샘플이 준비됩니다.
4. 첫 메뉴인 FTP 자료 수신 화면에서 **전체 파이프라인 실행**을 누릅니다.
5. 완료된 실행 건의 **폴더** 버튼으로 통계 결과와 Report를 확인합니다.
6. 다시 실행하면 완료 이력으로 건너뜁니다.

설치 실패 시 명령 프롬프트에서 실행해 오류를 확인하세요. Python 경로를 직접 지정하려면 Electron 실행 전에 `ATLAS_PYTHON` 환경변수를 설정할 수 있습니다. 기본으로 패키지의 `.venv`를 사용합니다.

## 빠른 시작 — Linux

그래픽 데스크톱이 있는 환경에서 다음을 실행합니다.

```bash
./setup_linux.sh
./start_ui_linux.sh
```

화면 없이 Python 엔진만 실행하려면 다음과 같이 사용합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m CODE_Controller.cli demo
./manual_linux.sh
```

## 자동 실행과 수동 실행

- `manual_windows.bat` / `manual_linux.sh`: 전체 파이프라인 1회 실행.
- `auto_windows.bat` / `auto_linux.sh`: 계속 실행하며 기본 300초마다 새 자료 확인.
- `stop_auto_windows.bat` / `stop_auto_linux.sh`: 현재 처리 완료 후 자동 실행 중지.
- Electron의 **자동 실행 시작**: 화면과 독립된 Python 프로세스 실행. 화면을 닫아도 이 프로세스는 유지됩니다.
- Electron의 **자동 실행 중지**: 현재 작업 완료 후 중지 요청.

서버의 부팅 후 자동 시작·장애 시 재시작은 데모에서 OS에 등록하지 않습니다. 운영 배포 시 Windows 작업 스케줄러에서 `auto_windows.bat`를 시작하도록 구성하거나, Linux 서비스 관리자로 Python 엔진을 실행해야 합니다. 실제 등록은 별도 작업입니다.

같은 작업공간에서 서버와 수동 작업이 겹치면 파일 잠금으로 중복 실행을 막습니다. 서로 다른 사용자 PC가 같은 원격 업로드 영역에 독립적으로 작업하는 경우의 전역 중복 관리와 권한 정책은 후속 설계 대상입니다. 수동 작업을 실행하는 동안에는 화면을 유지하세요.

## 파이프라인과 화면

FTP 수신 → STDF 변환 → 기본 통계 → Report 생성 → 결과 업로드 → 완료 확인 → 보관기간 경과 중간 데이터 정리.

- 좌측: FTP가 1번인 처리 단계 메뉴.
- 우측 상단: 실행 관리·작업 설정·실행 이력·운영 로그 탭과 실행 제어.
- 우측 하단: 선택 단계의 작업 본문.
- 모의 전송은 FTP 접속 없이 로컬 폴더 사이에서 수신·업로드와 이력 처리를 실행합니다. 실제 FTP 전송과 명확하게 구분됩니다.

## 실제 FTP 연결

화면의 작업 설정 탭 또는 `config.json`에서 전송 방식을 FTP로 변경합니다. 서버 주소·포트·원본 경로·결과 경로를 지정하고 계정은 환경변수로 전달합니다.

```bat
set ATLAS_FTP_USER=your_username
set ATLAS_FTP_PASSWORD=your_password
```

FTP는 수동형 데이터 연결을 사용합니다. FTPS를 켜면 서버 인증서를 검증하는 명시적 FTPS 연결을 사용합니다. SFTP는 다른 프로토콜이며 포함하지 않았습니다. 서버는 MLSD 및 파일 크기 조회를 지원해야 합니다. 원본에는 `.stdf`와 `.std`를 수신합니다. 압축된 STDF는 이번 데모의 입력 지원 대상이 아닙니다.

로컬 수신 경로는 패키지 아래 `workspace/raw/<출처 식별자>`, 실행 결과는 `workspace/runs`입니다. 서로 다른 서버·원격 원본 폴더는 다른 출처 폴더를 사용해 같은 파일명 충돌을 피합니다. 임의 로컬 보관 루트 선택은 후속 설정 기능입니다. FTP 원본 파일이 수신 중 변경되면 크기·수정 시각 검사로 해당 수신을 실패 처리합니다. 이력에 완료된 같은 원격 경로는 로컬 파일이 정상인 한 재수신하지 않습니다. 원격 파일을 덮어써 새 버전으로 쓰는 업체는 새 파일명 정책 또는 이력 갱신 정책이 필요합니다.

## 독립 프로그램 실행

패키지 루트에서 가상환경의 Python으로 실행합니다. 아래 `python`은 해당 가상환경 인터프리터를 뜻합니다. 출력 폴더는 새 폴더를 지정해야 합니다.

```bash
python -m CODE_STDF_Converter --input /path/input.stdf --output /path/new_conversion
python -m CODE_Statistics --input /path/new_conversion/example_FULL.parquet --output /path/new_statistics
python -m CODE_Report --conversion /path/new_conversion/conversion.json --statistics /path/new_statistics --output /path/new_report
python -m CODE_FTP download
python -m CODE_FTP upload --run-id 실행번호
```

측정 파일 이름은 실제 변환 결과의 `conversion.json`의 `data_path`에서 확인하세요. 변환 CLI의 `--format csv` 옵션으로 기존 CSV를 생성할 수 있습니다. 독립 Report의 링크를 그대로 쓰려면 변환·통계·Report 폴더를 공통 부모 아래 `conversion`, `statistics`, `report`로 배치해야 합니다. UI와 Controller는 이 구조를 자동으로 사용합니다.

Controller를 통한 단계별 실행도 지원합니다.

```bash
python -m CODE_Controller.cli run --stage download
python -m CODE_Controller.cli run --stage convert --input /path/input.stdf
python -m CODE_Controller.cli run --stage statistics --run-id 실행번호
python -m CODE_Controller.cli run --stage report --run-id 실행번호
python -m CODE_Controller.cli run --stage upload --run-id 실행번호
```

성공한 단계는 파일 목록·크기·해시를 확인한 뒤 건너뛰며 같은 실행 건에서 다시 덮어쓰지 않습니다. 완료 결과가 누락되거나 손상되면 전체 파이프라인은 원본에서 새 실행 건을 생성합니다. 수동 단계 실행은 검증 오류를 안내하므로 새 변환 건을 선택해야 합니다. 변경된 결과는 새 실행 건 또는 독립 프로그램의 새 출력 폴더로 생성합니다. 실패한 단계는 같은 실행 건에서 재시도할 수 있습니다. Controller는 선행 단계와 입력 파일 해시를 확인합니다. 중단된 단계는 다음 실행 때 실패 상태로 복구합니다. 독립 변환·통계·Report CLI는 Controller 이력에 자동 등록하지 않습니다. FTP 업로드 CLI는 등록된 실행 건의 업로드 상태를 갱신합니다. 잘못된 설정도 작업 설정 탭에서 새 설정으로 복구할 수 있으며, 자동 엔진은 실행 중 설정 오류를 기록하고 다음 주기에 다시 확인합니다.

## 결과물과 중간 데이터 정리

- `conversion/conversion.json`: 원본·중간 데이터 해시, 출력 포맷·압축·프로그램 정보, 처리 시간과 기존 엔진 기록.
- `statistics/summary.json`: 전체 측정 행 기준 수율·BIN 집계.
- `statistics/histograms.json`, `histograms.html`: 500개 테스트 등 전체 실제 사용 열의 히스토그램. HTML에서 항목 선택 가능.
- `statistics/map.json`, `map.svg`: 좌표 맵. 같은 좌표는 마지막 측정 행을 표시.
- `statistics/statistics.xlsx`: 수율 요약·테스트 통계·BIN 집계·맵 데이터 4개 시트.
- `statistics/measurements.xlsx`: 전체 가로형 측정값·테스트 정의·자료 안내. 최종 결과물로 업로드하고 보존합니다.
- `report/index.html`, `report.json`: 독립 Report 페이지와 생성 기록.
- `complete.json`: 최종 결과물 목록·크기·해시. FTP 업로드에서 마지막으로 게시.

수율은 전체 PRR 측정 행 기준이므로 재시험을 포함합니다. 최신 좌표 기준 수율 또는 최초 시험 수율로 오해하지 마세요. 테스트별 한계 이탈 수는 표시된 리밋과 측정값의 비교이며 DUT 전체 판정과 별개입니다. 통계 계산은 원본 엔진이 CSV에 기록한 값과 단위를 그대로 사용합니다.

중간 데이터 정리는 기본 7일 후이며 설정에서 변경 가능합니다. **0일은 완료 직후 정리**를 뜻합니다. 변환·통계·Report·업로드가 성공하고 원본과 로컬 최종 결과물의 해시가 맞을 때만 해당 실행 폴더의 Parquet 또는 CSV를 삭제합니다. 원본 STDF, 최종 결과물, 변환 기록은 남깁니다. 손상된 실행은 정리를 보류하고 다른 정상 실행은 계속 정리합니다. 독립 변환·통계 CLI 결과는 자동 정리 대상에 등록되지 않습니다. 독립 FTP 업로드는 Controller와 같은 잠금·이력·선행 검증을 사용합니다. 모의·실제 업로드 모두 중간 Parquet/CSV 자체는 전송하지 않습니다.

FTP 전송 실패는 다음 자동 주기 또는 수동 실행에서 재시도합니다. 부분 파일은 완료 목록으로 공개하지 않습니다. FTP 업로드 검증은 전송 응답·크기를 확인하며, 서버에 저장된 해시의 재다운로드 검증은 구현하지 않았습니다. 업로드 후 원격 파일의 외부 삭제나 변조 감지는 후속 검증 정책이 필요합니다.

## 검증

```bash
python -m unittest CODE_Tests.test_pipeline CODE_Tests.test_review -v
python -m pip install -r CODE_Tests/requirements.txt
python -m unittest CODE_Tests.test_ftp -v
cd CODE_UI
npm run check
```

실제 합성 STDF로 96개 칩·500개 테스트, 양품 87개·불량 9개·수율 90.625%를 확인했습니다. 이력 기반 건너뛰기, 입력 무결성 검사, 잘린 원본 실패 처리, 실패·손상 결과의 정리 제외, 서버 정상 중지를 검증했습니다. 로컬 FTP 서버를 통한 실제 FTP 수신·업로드도 검증했습니다.

Electron IPC 명령 경계는 창 객체를 대체하고 실제 Python 프로세스와 연결해 검증했습니다. 화면은 Chromium에서 실제 Python 명령에 연결해 1440px·1100px 폭과 메뉴·탭·로그·Report 렌더링을 확인했습니다. 이 실행 환경에서는 네이티브 Electron 창이 실행 중 종료되어 네이티브 창 검증은 완료하지 못했습니다. 실제 Windows PC와 운영 FTP/FTPS 연결은 별도 확인이 필요합니다.

`CODE_Tests/ui_smoke.cjs`는 그래픽 데스크톱 환경에서 실제 Electron 창 검증용입니다. `CODE_Tests/browser_ui.cjs`는 별도 시험용 Chromium 패키지 경로가 필요한 렌더러 시험입니다. 시험 대체 연결은 배포 UI에 포함되지 않습니다.

샘플은 합성 자료이며 실제 장비 성능이나 양산 수율을 나타내지 않습니다. 통계의 측정값은 배치 처리하지만 기존 파서와 맵 메타데이터의 메모리 사용은 파일 규모에 따라 늘어납니다. 최대 양산 파일·장기간 운영·로그 보존 주기·디스크 용량 제한은 후속 검증 항목입니다.

## 수정 범위를 줄이는 코드 구조

[구성요소와 변경 위치](CODE_Docs/MODULE_MAP.md)에 기능별 파일과 계약을 정리했습니다. 기존 변환 엔진을 그대로 보존하고 새 기능은 어댑터에서 연결해 변경 범위를 제한합니다. 실행 가능한 데모의 최신 요구사항은 [요구사항](CODE_Docs/REQUIREMENTS.md)에 기록했습니다.

## Parquet 출력 규칙

기본 설정은 `intermediate_format: "parquet"`입니다. UI의 작업 설정에서 Parquet/CSV를 선택하며, 포맷을 바꾸면 같은 원본도 별도 실행 건으로 처리합니다.

- 한 STDF의 실제 사용 테스트만 가로형 열로 저장합니다. 99999개 열을 미리 만들지 않습니다.
- 측정값은 float64, 측정 누락·비유한 값은 null입니다. 원본 변환 엔진이 CSV에 기록한 유효 수치의 정밀도를 유지합니다.
- `col_0001` 등 열 식별자를 사용하고 원본 테스트 번호·이름·단위·리밋은 파일 메타데이터에 보존합니다. 같은 번호의 다른 열을 합치지 않습니다.
- LOT·프로그램·프로그램 버전·원본 해시는 Parquet 메타데이터와 conversion.json에서 추적합니다.
- ZSTD 레벨 3, 최대 4096행 단위의 행 그룹으로 기록합니다. 파일 전체를 새 데이터프레임에 적재하지 않습니다.
- 기존 엔진 연결에 필요한 CSV는 Parquet과 변환 기록이 정상 확정된 뒤 즉시 제거합니다. 실패 시 연결 CSV를 남겨 완료 처리하지 않습니다. 운영 보관기간은 이후 Parquet에 적용됩니다.
- 원본 STDF는 변환·압축하거나 삭제하지 않습니다. 히스토그램·맵·YIELD·통계 Excel·HTML Report를 생성하고 전체 측정값 Excel도 추가합니다.

기존 파서가 CSV를 먼저 생성하므로 디스크에 원본·연결 CSV·Parquet을 동시에 둘 공간이 잠시 필요합니다. 직접 STDF → Parquet 출력은 기존 엔진 변경이 필요한 후속 최적화입니다. 용량과 속도의 실제 개선 폭은 파일별로 다르며 최대 양산 자료로 추가 측정해야 합니다.

설계·검증 세부 기록: [출력 포맷](CODE_Docs/DATA_FORMAT.md), [전체 리뷰 2회](CODE_Docs/REVIEW_2_PASSES.md), [검증 기록](CODE_Docs/VALIDATION.md).

## 전체 측정값 Excel

전체 측정값 출력은 기본으로 켜져 있습니다. `measurements.xlsx`에서 모든 실제 테스트 값을 확인할 수 있습니다. 첫 시트의 제목에는 테스트 번호·이름·단위·열 식별자가 있고, 식별 열 5개와 제목 행을 고정하며 필터를 제공합니다. 테스트 정의 시트에 번호·이름·단위·상하한을 따로 기록합니다.

최대 1048575개의 측정 행마다 다음 시트로 나눕니다. 16384열을 초과하면 오류를 안내합니다. 큰 자료의 Excel 생성 시간이 부담되면 작업 설정의 **전체 측정값 Excel도 생성**을 해제하거나 독립 통계 CLI에 `--no-measurement-excel`을 지정하세요. 정확한 스크립트 처리 기준은 Parquet이며 Excel은 확인용입니다. 전체 측정값 Excel도 최종 결과물이므로 임시 데이터 정리 대상에서 제외합니다.
