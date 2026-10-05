import datetime
import json
import os

from . import config

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def render_markdown(findings: list, scan_target: str) -> str:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# ATE Watchdog 스캔 리포트",
        "",
        f"- 스캔 시각: {ts}",
        f"- 스캔 대상: `{scan_target}`",
        f"- 발견된 이슈 수: {len(findings)}",
        "",
    ]
    if not findings:
        lines.append("이슈가 발견되지 않았습니다.")
        return "\n".join(lines)

    by_sev = {"high": [], "medium": [], "low": []}
    for f in findings:
        by_sev.setdefault(f.severity, []).append(f)

    for sev in ("high", "medium", "low"):
        items = by_sev.get(sev, [])
        if not items:
            continue
        label = {"high": "높음", "medium": "중간", "low": "낮음"}[sev]
        lines.append(f"## 심각도: {label} ({len(items)}건)")
        lines.append("")
        for f in items:
            rel = os.path.relpath(f.file_path)
            lines.append(f"### [{f.finding_id}] {f.rule_id} — `{rel}:{f.line}`")
            lines.append(f"{f.message}")
            if f.suggested_fix:
                lines.append("")
                lines.append("제안 수정(diff):")
                lines.append("```diff")
                lines.append(f.suggested_fix)
                lines.append("```")
            lines.append("")
    lines.append("---")
    lines.append(
        "> 이 리포트의 수정안은 제안일 뿐이며, 명시적 승인(Rule1) 없이는 "
        "`apply.py`가 어떤 파일도 변경하지 않습니다."
    )
    return "\n".join(lines)


def write_report(findings: list, scan_target: str) -> tuple:
    """MD 리포트(사람용)와 JSON 사이드카(apply 단계가 읽는 기계용)를 함께 기록한다."""
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = os.path.join(config.REPORTS_DIR, f"scan_{ts}.md")
    json_path = os.path.join(config.REPORTS_DIR, f"scan_{ts}.json")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(findings, scan_target))

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([x.to_dict() for x in findings], f, ensure_ascii=False, indent=2)

    return md_path, json_path
