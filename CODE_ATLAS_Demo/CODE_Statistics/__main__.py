import argparse
from .service import generate

p = argparse.ArgumentParser(description="가로형 Parquet / CSV → 히스토그램·맵·수율·통계시트")
p.add_argument("--input", required=True)
p.add_argument("--output", required=True)
p.add_argument("--bins", type=int, default=20)
p.add_argument("--no-measurement-excel", action="store_true", help="전체 측정값 Excel 출력 제외")
a = p.parse_args()
if not 2 <= a.bins <= 200:
    p.error("히스토그램 구간은 2~200입니다.")
print(generate(a.input, a.output, a.bins, measurement_excel=not a.no_measurement_excel))
