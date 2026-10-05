"""정기 모니터링 루프: 설정된 주기마다 스캔을 재실행하고 새 리포트를 남긴다.

이전 스캔 대비 새로 발생/해소된 이슈 수를 콘솔에 요약 출력한다.
"""

import time

from . import analyzer, config, report


def run_once(target_dir: str = None):
    target_dir = target_dir or config.DEFAULT_SCAN_TARGET
    findings = analyzer.scan_target(target_dir)
    md_path, json_path = report.write_report(findings, target_dir)
    return findings, md_path, json_path


def watch(target_dir: str = None, interval_seconds: int = None, max_cycles: int = None):
    interval_seconds = interval_seconds or config.MONITOR_INTERVAL_SECONDS
    max_cycles = config.MONITOR_MAX_CYCLES if max_cycles is None else max_cycles

    prev_count = None
    cycle = 0
    while True:
        cycle += 1
        findings, md_path, _json_path = run_once(target_dir)
        delta = "" if prev_count is None else f" (이전 대비 {len(findings) - prev_count:+d})"
        print(f"[watch #{cycle}] 이슈 {len(findings)}건{delta} -> {md_path}")
        prev_count = len(findings)

        if max_cycles and cycle >= max_cycles:
            break
        time.sleep(interval_seconds)
