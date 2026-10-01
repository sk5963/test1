"""ATE Watchdog CLI

사용 예:
  python -m ate_watchdog.cli scan
  python -m ate_watchdog.cli scan --target /path/to/ate/programs
  python -m ate_watchdog.cli apply --report CODE_PY/reports/scan_XXXX.json \\
      --ids FLOATEQ-0001,FLOATEQ-0002 --approve "승인, FLOATEQ 수정 적용"
  python -m ate_watchdog.cli watch --interval 300 --max-cycles 3
"""

import argparse
import sys

from . import analyzer, apply as apply_mod, config, monitor, report


def cmd_scan(args):
    target = args.target or config.DEFAULT_SCAN_TARGET
    findings = analyzer.scan_target(target)
    md_path, json_path = report.write_report(findings, target)
    print(f"이슈 {len(findings)}건 발견")
    print(f"- MD 리포트: {md_path}")
    print(f"- JSON(apply용): {json_path}")


def cmd_apply(args):
    ids = [x.strip() for x in args.ids.split(",") if x.strip()]
    try:
        applied = apply_mod.apply_findings(args.report, ids, args.approve)
    except apply_mod.ApprovalRequiredError as e:
        print(f"[거부됨] {e}", file=sys.stderr)
        sys.exit(1)
    print(f"적용 완료: {len(applied)}건 -> {applied}")
    skipped = set(ids) - set(applied)
    if skipped:
        print(f"적용 불가(수정안 없음/라인 불일치): {sorted(skipped)}")


def cmd_watch(args):
    monitor.watch(
        target_dir=args.target,
        interval_seconds=args.interval,
        max_cycles=args.max_cycles,
    )


def build_parser():
    p = argparse.ArgumentParser(prog="ate_watchdog")
    sub = p.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="1회 스캔 후 MD/JSON 리포트 생성")
    p_scan.add_argument("--target", default=None)
    p_scan.set_defaults(func=cmd_scan)

    p_apply = sub.add_parser("apply", help="명시적 승인 하에 제안된 수정 적용")
    p_apply.add_argument("--report", required=True, help="scan이 생성한 JSON 리포트 경로")
    p_apply.add_argument("--ids", required=True, help="콤마로 구분된 finding id 목록")
    p_apply.add_argument("--approve", required=True, help=f"'{config.APPROVAL_KEYWORD}' 단어를 포함한 승인 문구")
    p_apply.set_defaults(func=cmd_apply)

    p_watch = sub.add_parser("watch", help="정기 모니터링 루프 실행")
    p_watch.add_argument("--target", default=None)
    p_watch.add_argument("--interval", type=int, default=None)
    p_watch.add_argument("--max-cycles", type=int, default=None)
    p_watch.set_defaults(func=cmd_watch)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
