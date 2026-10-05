import argparse
from .service import convert

p = argparse.ArgumentParser(description="STDF → 가로형 Parquet 또는 기존 CSV 독립 변환")
p.add_argument("--input", required=True)
p.add_argument("--output", required=True)
p.add_argument("--format", choices=["parquet", "csv"], default="parquet")
a = p.parse_args()
print(convert(a.input, a.output, data_format=a.format)["data_path"])
