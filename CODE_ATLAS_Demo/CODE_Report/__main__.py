import argparse
from .service import generate

p = argparse.ArgumentParser(description="변환 기록과 통계 결과 → 독립 Report 페이지")
p.add_argument("--conversion", required=True)
p.add_argument("--statistics", required=True)
p.add_argument("--output", required=True)
a = p.parse_args()
print(generate(a.conversion, a.statistics, a.output))
