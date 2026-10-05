"""히스토그램 페이지와 맵 SVG 출력."""

import html
import json
from pathlib import Path


def save_map(path, cells):
    latest = {(c["x"], c["y"]): c for c in cells}
    if not latest:
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="500" height="100"><text x="20" y="50">좌표 정보 없음</text></svg>',
            encoding="utf-8",
        )
        return
    xs = [k[0] for k in latest]
    ys = [k[1] for k in latest]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    width = xmax - xmin + 1
    height = ymax - ymin + 1
    scale = min(44, 800 / max(width, height))
    body = []
    for (x, y), c in latest.items():
        px = 20 + (x - xmin) * scale
        py = 45 + (ymax - y) * scale
        color = "#14b8a6" if c["passed"] else "#f97373"
        title = html.escape(f"X={x}, Y={y}, BIN={c['sbin']}, 측정 행={c['row']}")
        body.append(
            f'<rect x="{px}" y="{py}" width="{scale * 0.86}" height="{scale * 0.86}" rx="2" fill="{color}"><title>{title}</title></rect>'
        )
    path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width * scale + 40} {height * scale + 65}"><rect width="100%" height="100%" fill="#f8fafc"/><text x="20" y="26" font-family="sans-serif" font-size="14">칩 맵 · 초록: 양품 / 빨강: 불량 · 동일 좌표 마지막 행</text>{"".join(body)}</svg>',
        encoding="utf-8",
    )


def save_histograms(path, tests):
    data = json.dumps(tests, ensure_ascii=False, allow_nan=False).replace(
        "<", "\\u003c"
    )
    page = (Path(__file__).parent / "templates" / "histograms.html").read_text(
        encoding="utf-8"
    )
    path.write_text(page.replace("__DATA__", data), encoding="utf-8")
