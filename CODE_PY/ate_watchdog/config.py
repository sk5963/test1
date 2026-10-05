"""ATE Watchdog 설정 - 모든 on/off 옵션은 이 파일 상단에서 관리한다 (Rule2)."""

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_CODE_PY_ROOT = os.path.dirname(_HERE)

# ── 기능 on/off 스위치 ──────────────────────────────────────────────
ENABLE_RULE_HARDCODED_LIMIT = True      # 하드코딩된 스펙 리밋(매직넘버) 탐지
ENABLE_RULE_NO_EXCEPT_ON_INSTR = True   # 계측기 통신 호출에 예외처리 누락 탐지
ENABLE_RULE_FLOAT_EQUALITY = True       # 부동소수점 '==' pass/fail 판정 탐지
ENABLE_RULE_NO_TIMEOUT = True           # 계측기 호출에 timeout 미지정 탐지
ENABLE_RULE_RESOURCE_NOT_CLOSED = True  # 계측기 리소스 open 후 close/teardown 누락 탐지
ENABLE_RULE_NO_BIN_LOG = True           # 측정 후 bin/log 호출 누락 탐지
ENABLE_RULE_LONG_FUNCTION = True        # 함수 라인 수 초과 탐지 (Rule3)

# 자동 수정 적용 게이트. False가 기본값이며, apply 단계는 명시적 승인
# 문자열이 없으면 절대 파일을 바꾸지 않는다 (Rule1 강제 지점).
REQUIRE_EXPLICIT_APPROVAL = True
APPROVAL_KEYWORD = "승인"  # CLI apply 명령에서 이 단어가 포함된 --approve 인자가 와야 적용됨

# ── 경로 설정 ───────────────────────────────────────────────────────
DEFAULT_SCAN_TARGET = os.path.join(_CODE_PY_ROOT, "sample_ate_programs")
REPORTS_DIR = os.path.join(_CODE_PY_ROOT, "reports")
CHANGELOG_PATH = os.path.join(_CODE_PY_ROOT, "CHANGELOG.md")

# ── 룰 임계값 ───────────────────────────────────────────────────────
LONG_FUNCTION_MAX_LINES = 80        # 이 라인수를 넘는 함수는 분리 권고 (Rule3, 최종 상한은 500~1000)
FLOAT_TOLERANCE_HINT = 1e-6         # 제안 diff에 사용할 기본 허용오차

# ── 모니터링 루프 설정 ──────────────────────────────────────────────
MONITOR_INTERVAL_SECONDS = 300      # 정기 스캔 주기 (기본 5분)
MONITOR_MAX_CYCLES = 0              # 0 = 무한 루프, N>0 이면 N회 후 종료 (테스트/디버그용)

# 계측기/통신 관련 함수로 간주할 이름 패턴 (휴리스틱 탐지에 사용)
INSTRUMENT_CALL_KEYWORDS = (
    "write", "query", "read", "ask", "send", "visa", "gpib", "scpi",
)
RESOURCE_OPEN_KEYWORDS = ("open_resource", "ResourceManager", "connect")
RESOURCE_CLOSE_KEYWORDS = ("close", "disconnect")
BIN_LOG_KEYWORDS = ("bin", "log_result", "write_result", "record_result")
