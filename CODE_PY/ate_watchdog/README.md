# ATE Watchdog

DDI칩 개발 ATE 엔지니어 업무를 위한 AI 능동 워크플로우 프레임워크.
Python 기반 ATE 테스트 프로그램을 정적분석하여 **문제점 탐지 → 알림(MD 리포트)
→ 수정안 제안(diff) → 명시적 승인 후에만 자동 적용 → 정기 모니터링** 까지의
파이프라인을 제공한다.

## 왜 이렇게 만들었나 (설계 원칙)

- **승인 없는 자동 수정 금지 (Rule1)**: `apply.py`는 `config.APPROVAL_KEYWORD`
  ("승인")가 포함된 문자열이 명시적으로 전달되지 않으면 `ApprovalRequiredError`를
  던지고 어떤 파일도 건드리지 않는다. 이 동작은 `config.REQUIRE_EXPLICIT_APPROVAL`
  로 끌 수 있지만 **운영 환경에서는 절대 False로 두지 말 것**.
- **모든 옵션은 `config.py` 상단에 (Rule2)**: 룰 on/off, 임계값, 경로, 모니터링
  주기가 전부 한 파일에 모여 있다.
- **함수/파일 분리 (Rule3)**: 룰 하나 = 함수 하나. 새 룰은 `rules.py`에
  `check_*` 함수로 추가하고 `analyzer.ALL_RULES`에 등록하면 된다.
- **적용 전 안전장치**: `apply.py`는 스캔 시점의 원본 라인(`original_snippet`)과
  현재 파일의 라인이 일치하는지 재확인한 뒤에만 수정한다. 스캔 이후 파일이
  바뀌었다면 조용히 건너뛴다(=잘못된 라인에 덮어쓰기 방지).

## 현재 탐지하는 7가지 룰

| 룰 ID | 심각도 | 자동수정 diff | 설명 |
|---|---|---|---|
| NOEXCEPT | high | - | 계측기 통신 호출이 try/except 밖에 있음 |
| FLOATEQ | high | O | 부동소수점 `==`/`!=` 판정 → `abs(a-b) < tol` 제안 |
| NOBINLOG | high | - | 테스트 함수에 bin/log 기록 호출 누락 |
| HARDLIMIT | medium | - | 스펙 판정에 하드코딩된 숫자 리밋 |
| NOTIMEOUT | medium | - | 계측기 호출에 timeout 미지정 |
| NOCLOSE | medium | - | 계측기 리소스 open 후 close 누락 |
| LONGFUNC | low | - | 함수가 임계 라인수(기본 80줄) 초과 (Rule3) |

현재 자동 diff 제안은 **FLOATEQ 룰만** 지원한다(기계적으로 안전하게 한 줄만
치환 가능한 경우로 범위를 제한). 나머지 룰은 사람이 판단해 고치도록 설명만
제공한다 — 잘못된 자동수정이 ATE 프로그램을 망가뜨리는 것을 막기 위함.

## 사용법

```bash
cd CODE_PY

# 1) 스캔 → MD(사람용 리포트) + JSON(apply용) 생성
python3 -m ate_watchdog.cli scan
python3 -m ate_watchdog.cli scan --target /path/to/real/ate_programs

# 2) 리포트(reports/scan_*.md)를 읽고 수정할 finding id를 고른다

# 3) 승인 문구 없이 시도 → 반드시 거부되어야 정상
python3 -m ate_watchdog.cli apply --report reports/scan_XXXX.json \
    --ids FLOATEQ-0007 --approve "that looks fine"
# [거부됨] 명시적 승인 문구('승인' 포함)가 없어 수정 적용을 거부함.

# 4) 승인 문구 포함 시 적용 + CHANGELOG.md에 기록
python3 -m ate_watchdog.cli apply --report reports/scan_XXXX.json \
    --ids FLOATEQ-0007 --approve "승인, FLOATEQ-0007 적용"

# 5) 정기 모니터링 (5분 주기, 무한 루프; Ctrl+C로 중지)
python3 -m ate_watchdog.cli watch
python3 -m ate_watchdog.cli watch --interval 60 --max-cycles 3   # 테스트용
```

## 실제 ATE 프로그램 연결하기

`config.DEFAULT_SCAN_TARGET`을 실제 테스트 프로그램 경로로 바꾸거나,
매번 `--target`으로 지정한다. `sample_ate_programs/`는 프레임워크 동작을
보여주기 위한 데모 파일이며 실제 생산 코드가 아니다.

## 알려진 제약 / 추후 영향받지 않도록 기록 (Rule5)

- **휴리스틱 기반 탐지**: `ast`로 패턴만 보고 판단하므로 오탐(false positive)이
  있을 수 있다. 예: 계측기와 무관한 함수명에 `read`/`write`가 들어가면
  NOEXCEPT/NOTIMEOUT이 오탐될 수 있음 — `config.INSTRUMENT_CALL_KEYWORDS`로
  범위를 좁혀서 조정할 것.
- **FLOATEQ 자동수정은 단일 라인 비교식에서만 동작**한다. 비교식이 여러 줄에
  걸쳐 있으면(`node.end_lineno != node.lineno`) `fixed_snippet`이 비워지고
  diff가 생성되지 않는다 — 의도된 동작이며, 이를 "버그"로 보고 멀티라인까지
  억지로 지원하려 하면 괄호 불균형 등으로 더 위험한 자동수정이 생길 수 있다.
- **apply는 멱등성 체크를 raw 라인 비교로만 한다**: 같은 파일에 공백만 바뀌는
  포맷터(black 등)를 스캔-적용 사이에 돌리면 모든 finding이 "라인 불일치"로
  조용히 skip된다. 이는 안전을 위한 의도된 보수적 동작이다.
