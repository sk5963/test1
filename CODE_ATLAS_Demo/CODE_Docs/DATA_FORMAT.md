# 측정 데이터 출력 기준

버전: 데모 0.2.1 / 계약 wide_measurements_v1

사용자의 최신 Parquet 요청을 반영한다. 기본 출력은 가로형 Parquet이며 기존 Full CSV는 호환 선택으로 남긴다. 결과물 뷰어·에디터는 별도 프로그램이다.

| 대상 | 보관 형식 | 처리 |
| --- | --- | --- |
| ATE 원본 | .stdf / .std | 수신 그대로 보관 |
| 임시 측정 데이터 | .parquet, ZSTD 레벨 3 | 통계·Report 생성 입력; 성공 업로드 후 기간 정리 |
| 기존 포맷 호환 | .csv | 설정 또는 변환 CLI --format csv로 선택 |
| 차트·맵 데이터 | JSON | 기존 고정 결과 형식 유지 |
| 통계시트 | XLSX | 수율·테스트 통계·BIN·맵 4개 시트 |
| 전체 측정값 | XLSX | 전체 실제 테스트 측정값·테스트 정의·자료 안내; 업로드 후 보존 |
| Report | HTML + 생성 기록 JSON | 별도 페이지 |
| 실행·수신 기록 | SQLite | 서버와 수동 처리 이력 |

## 열과 메타데이터

한 행은 기존 엔진의 PRR 측정 행이다. 재시험도 별도 행으로 남는다. 실제 사용 테스트 수에 맞춰 열을 생성하며 테스트 번호를 배열 인덱스로 사용하지 않는다.

기본 부가 열은 기존 엔진의 part_id, temp, x_coord, y_coord, wafer_id, soft_bin, hard_bin, test_time, site, source_dataset, plot_ul이다. 원문 의미를 유지하는 문자열 열이며 사전 인코딩을 사용한다. 테스트 열은 col_0001, col_0002 등의 float64이다. 누락·비유한 값은 null이며 원본 STDF는 별도 보존한다.

Parquet 파일 메타데이터:

- atlas.format: wide_measurements_v1.
- atlas.header: 기본 열 목록과 테스트 열별 원본 번호·이름·단위·리밋·열 식별자.
- atlas.markers: 기존 CSV 완료·행 수·BIN 판정 기록.
- atlas.source_metadata: LOT·프로그램·프로그램 버전 등 기존 엔진 메타데이터와 원본 SHA-256.
- atlas.legacy_csv_sha256: 엔진 연결 CSV 생성 해시.

프로그램별 테스트 번호 차이는 원본 메타데이터와 열 정의로 추적한다. 다른 파일의 col_0001이 같은 테스트라는 가정은 하지 않는다. 번호가 같아도 이름 또는 열 위치가 다르면 독립 통계 열이다. 기존 엔진 내부의 동일 번호·동일 이름 통합 동작은 원본 코드의 정책을 그대로 따른다.

## 처리와 검증

원본 STDF → 기존 엔진의 연결 CSV → Parquet 정상 기록 → 변환 기록 확정 → 연결 CSV 제거 → 통계 → Report → 최종 결과 업로드 → 보관기간 경과 Parquet 정리.

CSV 선택 시 연결 CSV가 그대로 중간 데이터이며 보관기간 정리를 적용한다. Parquet 기록은 최대 4096행, 읽기는 1024행 단위 배치를 사용한다. 테스트 정의는 파일 메타데이터에 한 번 저장해 반복 저장 비용을 줄였다.

변환·통계·Report JSON은 스키마 버전 2로 출력한다. data_path/data_sha256/data_format이 실제 입력의 기준이다. 원본 엔진의 CSV 해시는 감사 기록이며 Parquet 파일 해시와 구분한다. 기존 CSV 스키마 1의 읽기 호환은 유지한다.

정리에는 원본의 존재·해시, 4개 처리 단계 성공, 완료 목록과 최종 결과물 해시가 필요하다. Parquet 또는 CSV가 이미 정리된 정상 완료 건은 최종 결과만 검증해 건너뛴다. 결과가 손상되면 원본에서 새 실행 건을 생성한다.

일반·모의 FTP 업로드는 최종 결과물만 전송한다. 중간 측정 데이터는 전송하지 않는다. 원격에서 Parquet 측정 데이터 자체를 장기 보관해야 한다는 요구가 추가되면 업로드·정리 정책을 별도로 변경한다.

## 범위와 참고

Parquet 파일의 크기는 행 수·사용 열 수·측정 분포·문자열 반복률·메타데이터에 따라 달라진다. 작은 파일은 메타데이터 비중이 커지므로 항상 CSV보다 작다는 보장은 하지 않는다. 기존 엔진 연결 CSV 생성 비용은 남아 있다. 원본 파서와 맵 메타데이터의 메모리 사용은 파일 크기에 따라 증가한다.

[Apache Arrow Parquet 문서](https://arrow.apache.org/docs/python/parquet.html) · [ParquetWriter 압축·배치·메타데이터 API](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetWriter.html)

전체 측정값 Excel도 최종 결과물이다. 설정으로 생성을 제외할 수 있으며 이 옵션 변경은 새 실행 건을 만든다. 전체 측정값 Excel은 1048575개 데이터 행마다 다음 시트를 생성하고, 16384열을 넘으면 출력 제외 설정을 안내한다. [Microsoft Excel 사양](https://support.microsoft.com/ko-kr/excel/excel-specifications-and-limits)
