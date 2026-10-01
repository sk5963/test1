"""승인된 수정만 실제 파일에 반영하는 게이트 (Rule1 강제 지점).

이 모듈의 apply_findings() 는 approval_text 인자에 config.APPROVAL_KEYWORD
("승인")가 포함되어 있지 않으면 어떤 파일도 건드리지 않고 즉시 거부한다.
"""

import datetime
import json
import os

from . import config
from .models import Finding


class ApprovalRequiredError(Exception):
    pass


def _check_approval(approval_text: str):
    if not config.REQUIRE_EXPLICIT_APPROVAL:
        return
    if not approval_text or config.APPROVAL_KEYWORD not in approval_text:
        raise ApprovalRequiredError(
            f"명시적 승인 문구('{config.APPROVAL_KEYWORD}' 포함)가 없어 수정 적용을 거부함. "
            "예: --approve '승인, FLOATEQ-0001 적용'"
        )


def load_findings_json(json_path: str) -> list:
    with open(json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [Finding.from_dict(d) for d in raw]


def apply_findings(json_path: str, finding_ids: list, approval_text: str) -> list:
    """반환값: 실제로 수정 적용된 finding_id 리스트."""
    _check_approval(approval_text)

    findings = load_findings_json(json_path)
    target_ids = set(finding_ids)
    applied = []

    for f in findings:
        if f.finding_id not in target_ids:
            continue
        if not f.fixed_snippet:
            continue
        with open(f.file_path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        idx = f.line - 1
        if idx < 0 or idx >= len(lines):
            continue
        original_line = lines[idx].rstrip("\n")
        if original_line != f.original_snippet:
            # 스캔 이후 파일이 바뀌어 라인이 더 이상 일치하지 않으면 건너뛴다 (안전장치)
            continue
        lines[idx] = f.fixed_snippet + "\n"
        with open(f.file_path, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        applied.append(f.finding_id)
        _append_changelog(f, approval_text)

    return applied


def _append_changelog(finding: Finding, approval_text: str):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rel = os.path.relpath(finding.file_path)
    entry = (
        f"\n## {ts} — {finding.finding_id} ({finding.rule_id})\n"
        f"- 파일: `{rel}:{finding.line}`\n"
        f"- 내용: {finding.message}\n"
        f"- 변경 전: `{finding.original_snippet.strip()}`\n"
        f"- 변경 후: `{finding.fixed_snippet.strip()}`\n"
        f"- 승인 문구: {approval_text}\n"
    )
    os.makedirs(os.path.dirname(config.CHANGELOG_PATH), exist_ok=True)
    header_needed = not os.path.exists(config.CHANGELOG_PATH)
    with open(config.CHANGELOG_PATH, "a", encoding="utf-8") as f:
        if header_needed:
            f.write("# ATE Watchdog 변경 이력\n")
            f.write("자동 적용된 모든 수정은 이 파일에 append-only로 기록된다 (Rule5).\n")
        f.write(entry)
