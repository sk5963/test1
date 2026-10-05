import ast
import os

from . import config, rules

ALL_RULES = (
    rules.check_hardcoded_limit,
    rules.check_no_except_on_instr,
    rules.check_float_equality,
    rules.check_no_timeout,
    rules.check_resource_not_closed,
    rules.check_no_bin_log,
    rules.check_long_function,
)


def _iter_python_files(target_dir: str):
    for root, _dirs, files in os.walk(target_dir):
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


def scan_file(file_path: str) -> list:
    with open(file_path, "r", encoding="utf-8") as f:
        source = f.read()
    source_lines = source.splitlines()
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError as e:
        from .models import Finding
        return [Finding(
            finding_id="SYNTAX-0001",
            file_path=file_path,
            line=e.lineno or 1,
            rule_id="SYNTAXERROR",
            severity="high",
            message=f"파일 파싱 실패: {e.msg}",
        )]

    findings = []
    for rule_fn in ALL_RULES:
        findings.extend(rule_fn(tree, source_lines, file_path))
    return findings


def scan_target(target_dir: str = None) -> list:
    target_dir = target_dir or config.DEFAULT_SCAN_TARGET
    all_findings = []
    for file_path in _iter_python_files(target_dir):
        all_findings.extend(scan_file(file_path))
    return all_findings
