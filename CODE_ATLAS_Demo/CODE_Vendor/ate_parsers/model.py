"""파서와 호출 프로그램 사이의 공통 데이터 계약.

연결 순서: WideDataset.tests -> TestColumn.key <- PartRow.values의 key.
Test Number는 중복될 수 있으므로 test_num이나 목록 위치로 측정값을 연결하지 않는다.
필드명/타입 변경은 앱 캐시와 외부 소비자에도 영향을 준다. 설명 보강과 스키마 변경을
구분하고, 스키마 변경 시 기존 import 별칭과 캐시 버전도 함께 검토한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import MutableMapping


@dataclass(slots=True)
class TestColumn:
    """한 측정 열의 정의. 실제 측정값은 PartRow.values에 따로 저장한다.

    key: 한 dataset 안의 연결 키. 현재 '번호_출현순번'이지만 문자열을 분해하지 말 것.
    test_num/title: 원본 테스트 번호와 표시 이름. 둘 다 단독 고유키가 아니다.
    pin: 핀 이름/번호 문자열. 입력이나 그룹화 옵션에 따라 빈 문자열이다.
    record_type: PTR/MPR/FTR 등. DataLog DC/FT는 PTR/FTR로 변환된다.
    unit: 소비자가 사용할 표시 단위. raw_unit/scaler와 중복 적용하지 않는다.
    lo_limit/hi_limit: 파서가 변환한 하한/상한. None은 미지정이며 0과 다르다.
    scaler/raw_unit: STDF 변환에 사용한 접두어/원본 단위 등 출처 정보.
        측정값은 이미 파서를 거친 값이므로 scaler를 무조건 다시 곱하지 않는다.
    """
    key: str
    test_num: int
    title: str
    pin: str = ""
    record_type: str = "PTR"
    unit: str = ""
    lo_limit: float | None = None
    hi_limit: float | None = None
    scaler: str = ""
    raw_unit: str = ""


@dataclass(slots=True)
class PartRow:
    """한 DUT 측정 결과. 같은 좌표의 재측정도 별도 행으로 보존한다.

    index: 파싱된 행의 0 기반 순번. 원본 라인 번호가 아니다.
    shot: 동시 측정 그룹. DataLog Sample # 또는 STDF PIR 그룹/보완 규칙으로 생성.
    sample: DataLog 원본 Sample #; STDF에서는 None.
    x/y: 맵 좌표. 미제공 좌표는 None; 0은 유효 좌표이다.
    test_time_ms: 측정 시간(ms), 없으면 None.
    real_time: 기존 원본 매핑을 유지하는 문자열. 표준 타임스탬프라고 가정하지 말 것.
    hbin/sbin: Hard/Soft BIN 번호. DataLog에서는 Category로 sbin을 유도한다.
    site: 원본 Site/DUT 번호, 파서의 정보 부재 대체값은 0.
    part_id: 원본 부품 식별자. 없으면 빈 문자열이다.
    passed: DUT 단위 판정. STDF BIN 규칙과 DataLog 측정/Category 규칙을 따른다.
        표시 리밋으로 새로 계산한 판정과 반드시 같다고 가정하지 않는다.
    category: DataLog 원본 Category 문자열; STDF 기본값은 빈 문자열.
    values: {TestColumn.key: 측정값}. 누락 측정은 키가 없을 수 있다.
        FTR 값은 0=PASS, 1=FAIL이며 DUT 전체 passed와는 다른 수준의 정보이다.
    """
    index: int
    shot: int
    sample: int | None
    x: int | None
    y: int | None
    test_time_ms: int | None
    real_time: str
    hbin: int | None
    sbin: int | None
    site: int
    part_id: str
    passed: bool
    category: str = ""
    values: MutableMapping[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if len(self.values) >= 512:
            from .numeric_values import NumericValues
            self.values = NumericValues(self.values)

    @property
    def cord(self) -> str:
        """좌표 표시용 'x_y'; 좌표가 없으면 ''. 재측정 때문에 행 고유키가 아니다."""
        if self.x is None or self.y is None:
            return ""
        return f"{self.x}_{self.y}"


@dataclass(slots=True)
class WideDataset:
    """두 파일 포맷이 공통으로 반환하는 결과. UI/히스토그램 객체를 담지 않는다.

    source_path/source_type: 입력 경로와 'STDF' 또는 'DataLog'.
    metadata: 포맷별 수집 정보. 항상 같은 키가 있다고 가정하지 말고 .get() 사용.
    tests/parts: 테스트 정의와 측정 행. 연결은 test_map()과 part.values로 수행.
        좌표가 있는 CP 입력은 기존 좌표 정책으로 무좌표 DUT가 제외될 수 있다.
        모든 원본 레코드의 보존 모델이 아니다. 원본 파일과 경고를 함께 보존한다.
    warnings: 파서가 수집한 경고. 빈 목록이 파일의 완전한 유효성을 보증하지 않는다.
    record_counts: STDF 'REC_TYP/REC_SUB'별 건수. DataLog 기본값은 빈 dict.
    _storage_projection_cache: 앱에서 사용하는 내부 파생 캐시. 외부 연동에 쓰지 않는다.
    """
    source_path: Path
    source_type: str
    metadata: dict[str, str]
    tests: list[TestColumn]
    parts: list[PartRow]
    warnings: list[str] = field(default_factory=list)
    record_counts: dict[str, int] = field(default_factory=dict)
    _storage_projection_cache: Any = field(default=None, repr=False)

    def test_map(self) -> dict[str, TestColumn]:
        """part.values의 키를 TestColumn으로 해석하는 조회용 딕셔너리."""
        return {test.key: test for test in self.tests}

    def public_info(self) -> dict[str, Any]:
        """전체 보존 행 기준 요약. 최신 좌표 필터/재측정 제외 수율이 아니다."""
        passed = sum(part.passed for part in self.parts)
        return {
            "source": str(self.source_path),
            "source_type": self.source_type,
            "parts": len(self.parts),
            "tests": len(self.tests),
            "pass": passed,
            "fail": len(self.parts) - passed,
            "warnings": list(self.warnings),
        }
