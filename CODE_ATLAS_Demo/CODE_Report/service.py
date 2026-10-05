"""독립 결과물인 정적 Report 페이지. 자동화 UI 내부에는 표시하지 않는다."""

import html
from string import Template
from pathlib import Path
from CODE_Common.io import read_json, write_json, now, VERSION, digest


def generate(conversion_path, statistics_path, output):
    c = read_json(conversion_path)
    s = read_json(Path(statistics_path) / "summary.json")
    if c.get("data_sha256", c["csv_sha256"]) != s.get("data_sha256", s["csv_sha256"]):
        raise ValueError("통계 결과의 입력 데이터가 변환 결과와 다릅니다.")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)

    def e(value):
        return html.escape(str(value))

    details = [
        ("원본 파일", Path(c["source"]).name),
        ("프로그램", c["metadata"].get("program", "미지정")),
        ("프로그램 버전", c["metadata"].get("job_rev", "미지정")),
        ("LOT", c["metadata"].get("lotid", "미지정")),
        ("변환 시각", c["created"]),
        ("변환 시간", str(c["duration_seconds"]) + "초"),
        ("원본 크기", f"{c['stdf_bytes']:,} 바이트"),
        ("중간 데이터 포맷", c.get("data_format", "csv").upper()),
        ("중간 데이터 압축", c.get("compression") or "없음"),
        ("중간 데이터 크기", f"{c.get('data_bytes', c['csv_bytes']):,} 바이트"),
        ("원본 SHA-256", c["source_sha256"]),
        ("중간 데이터 SHA-256", c.get("data_sha256", c["csv_sha256"])),
    ]
    rows = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in details)
    policy = e(s["yield_policy"])
    template = Template(
        (Path(__file__).parent / "templates" / "report.html").read_text(
            encoding="utf-8"
        )
    )
    page = template.substitute(
        {
            "lot": e(c["metadata"].get("lotid", "")),
            "source_name": e(Path(c["source"]).name),
            "total": format(s["total"], ","),
            "passed": format(s["passed"], ","),
            "yield_percent": format(s["yield_percent"], ".2f"),
            "tests": format(s["test_count"], ","),
            "rows": rows,
            "policy": policy,
            "version": VERSION,
            "missing": s["missing_coordinates"],
            "measurements_link": '<p><a href="../statistics/measurements.xlsx">전체 측정값 Excel 다운로드</a></p>' if s.get("measurement_excel") else "",
        }
    )
    (output / "index.html").write_text(page, encoding="utf-8")
    result = {
        "schema_version": 2,
        "tool_version": VERSION,
        "created": now(),
        "source_sha256": c["source_sha256"],
        "csv_sha256": c["csv_sha256"],
        "data_sha256": c.get("data_sha256", c["csv_sha256"]),
        "data_format": c.get("data_format", "csv"),
        "report_sha256": digest(output / "index.html"),
    }
    write_json(output / "report.json", result)
    return result
