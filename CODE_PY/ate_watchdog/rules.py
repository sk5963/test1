"""ATE Python 테스트 프로그램 정적분석 룰 모음.

각 check_* 함수는 (tree, source_lines, file_path) -> list[Finding] 시그니처를
가진다. 새 룰 추가 시 이 모듈에 함수를 추가하고 analyzer.ALL_RULES 에 등록한다.
"""

import ast
import difflib

from . import config
from .models import Finding

_counter = {"n": 0}


def _next_id(rule_id: str) -> str:
    _counter["n"] += 1
    return f"{rule_id}-{_counter['n']:04d}"


def _make_diff(file_path: str, line_no: int, old_line: str, new_line: str) -> str:
    diff = difflib.unified_diff(
        [old_line + "\n"], [new_line + "\n"],
        fromfile=f"{file_path}:{line_no}", tofile=f"{file_path}:{line_no} (fixed)",
        lineterm="",
    )
    return "\n".join(diff)


def check_hardcoded_limit(tree, source_lines, file_path):
    if not config.ENABLE_RULE_HARDCODED_LIMIT:
        return []
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        parent_is_spec_safe = any(
            isinstance(c, ast.Constant) and isinstance(c.value, (int, float))
            for c in [node.left] + node.comparators
        )
        has_name_source = any(
            isinstance(c, (ast.Name, ast.Attribute)) for c in [node.left] + node.comparators
        )
        if not (parent_is_spec_safe and has_name_source):
            continue
        literal = next(
            c for c in [node.left] + node.comparators
            if isinstance(c, ast.Constant) and isinstance(c.value, (int, float))
        )
        findings.append(Finding(
            finding_id=_next_id("HARDLIMIT"),
            file_path=file_path,
            line=node.lineno,
            rule_id="HARDLIMIT",
            severity="medium",
            message=(
                f"스펙 판정에 하드코딩된 리밋값({literal.value})이 사용됨. "
                "spec/config 파일에서 로드하도록 분리 권고."
            ),
        ))
    return findings


def check_no_except_on_instr(tree, source_lines, file_path):
    if not config.ENABLE_RULE_NO_EXCEPT_ON_INSTR:
        return []
    findings = []
    try_ranges = [
        (n.lineno, n.body[-1].end_lineno if n.body else n.lineno)
        for n in ast.walk(tree) if isinstance(n, ast.Try)
    ]

    def _in_try(line_no):
        return any(start <= line_no <= end for start, end in try_ranges)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = ""
        if isinstance(node.func, ast.Attribute):
            func_name = node.func.attr.lower()
        elif isinstance(node.func, ast.Name):
            func_name = node.func.id.lower()
        if not any(kw in func_name for kw in config.INSTRUMENT_CALL_KEYWORDS):
            continue
        if _in_try(node.lineno):
            continue
        findings.append(Finding(
            finding_id=_next_id("NOEXCEPT"),
            file_path=file_path,
            line=node.lineno,
            rule_id="NOEXCEPT",
            severity="high",
            message="계측기 통신 호출이 try/except 없이 실행됨. 통신 실패 시 전체 테스트가 중단될 위험.",
        ))
    return findings


def check_float_equality(tree, source_lines, file_path):
    if not config.ENABLE_RULE_FLOAT_EQUALITY:
        return []
    findings = []
    full_source = "\n".join(source_lines)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
            continue
        operands = [node.left] + node.comparators
        float_const = next(
            (c for c in operands if isinstance(c, ast.Constant) and isinstance(c.value, float)),
            None,
        )
        if float_const is None:
            continue

        line_idx = node.lineno - 1
        old_line = source_lines[line_idx] if line_idx < len(source_lines) else ""
        new_line = ""
        suggested = ""
        # 단일 라인 비교식일 때만 컬럼 오프셋으로 정밀 치환 (멀티라인 식은 자동수정 미제공)
        if old_line and node.end_lineno == node.lineno:
            left_expr = ast.get_source_segment(full_source, node.left)
            right_expr = ast.get_source_segment(full_source, node.comparators[0])
            if left_expr and right_expr:
                is_noteq = isinstance(node.ops[0], ast.NotEq)
                op_text = ">=" if is_noteq else "<"
                replacement = (
                    f"abs(({left_expr}) - ({right_expr})) {op_text} "
                    f"{config.FLOAT_TOLERANCE_HINT}"
                )
                new_line = old_line[:node.col_offset] + replacement + old_line[node.end_col_offset:]
                suggested = _make_diff(file_path, node.lineno, old_line, new_line)

        findings.append(Finding(
            finding_id=_next_id("FLOATEQ"),
            file_path=file_path,
            line=node.lineno,
            rule_id="FLOATEQ",
            severity="high",
            message="부동소수점 값을 '=='로 비교. 허용오차(tolerance) 비교로 변경 필요.",
            suggested_fix=suggested,
            original_snippet=old_line,
            fixed_snippet=new_line,
        ))
    return findings


def check_no_timeout(tree, source_lines, file_path):
    if not config.ENABLE_RULE_NO_TIMEOUT:
        return []
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = node.func.attr.lower() if isinstance(node.func, ast.Attribute) else (
            node.func.id.lower() if isinstance(node.func, ast.Name) else ""
        )
        if not any(kw in func_name for kw in ("open_resource", "query", "write")):
            continue
        has_timeout = any(kw.arg == "timeout" for kw in node.keywords)
        if has_timeout:
            continue
        findings.append(Finding(
            finding_id=_next_id("NOTIMEOUT"),
            file_path=file_path,
            line=node.lineno,
            rule_id="NOTIMEOUT",
            severity="medium",
            message="계측기 호출에 timeout 미지정. 통신 행 시 테스트가 무한 대기할 수 있음.",
        ))
    return findings


def check_resource_not_closed(tree, source_lines, file_path):
    if not config.ENABLE_RULE_RESOURCE_NOT_CLOSED:
        return []
    findings = []
    for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        opened_vars = set()
        for node in ast.walk(func):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                call = node.value
                callee = call.func.attr if isinstance(call.func, ast.Attribute) else (
                    call.func.id if isinstance(call.func, ast.Name) else ""
                )
                if callee in config.RESOURCE_OPEN_KEYWORDS and node.targets:
                    target = node.targets[0]
                    if isinstance(target, ast.Name):
                        opened_vars.add((target.id, node.lineno))
        if not opened_vars:
            continue
        func_src = ast.dump(func)
        has_with = any(isinstance(n, ast.With) for n in ast.walk(func))
        for var_name, open_line in opened_vars:
            closed = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr in config.RESOURCE_CLOSE_KEYWORDS
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == var_name
                for n in ast.walk(func)
            )
            if closed or has_with:
                continue
            findings.append(Finding(
                finding_id=_next_id("NOCLOSE"),
                file_path=file_path,
                line=open_line,
                rule_id="NOCLOSE",
                severity="medium",
                message=f"'{var_name}' 리소스가 open된 후 close()/disconnect() 호출이 없음 (with 블록 사용 권고).",
            ))
    return findings


def check_no_bin_log(tree, source_lines, file_path):
    if not config.ENABLE_RULE_NO_BIN_LOG:
        return []
    findings = []
    for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        if "test" not in func.name.lower():
            continue
        has_bin_log = any(
            isinstance(n, ast.Call)
            and (
                (isinstance(n.func, ast.Attribute) and any(kw in n.func.attr.lower() for kw in config.BIN_LOG_KEYWORDS))
                or (isinstance(n.func, ast.Name) and any(kw in n.func.id.lower() for kw in config.BIN_LOG_KEYWORDS))
            )
            for n in ast.walk(func)
        )
        if has_bin_log:
            continue
        findings.append(Finding(
            finding_id=_next_id("NOBINLOG"),
            file_path=file_path,
            line=func.lineno,
            rule_id="NOBINLOG",
            severity="high",
            message=f"테스트 함수 '{func.name}'에서 결과 bin/log 기록 호출이 발견되지 않음.",
        ))
    return findings


def check_long_function(tree, source_lines, file_path):
    if not config.ENABLE_RULE_LONG_FUNCTION:
        return []
    findings = []
    for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        end = getattr(func, "end_lineno", func.lineno)
        span = end - func.lineno
        if span <= config.LONG_FUNCTION_MAX_LINES:
            continue
        findings.append(Finding(
            finding_id=_next_id("LONGFUNC"),
            file_path=file_path,
            line=func.lineno,
            rule_id="LONGFUNC",
            severity="low",
            message=f"함수 '{func.name}'가 {span}줄로 기준({config.LONG_FUNCTION_MAX_LINES}줄)을 초과. 분리 권고 (Rule3).",
        ))
    return findings
