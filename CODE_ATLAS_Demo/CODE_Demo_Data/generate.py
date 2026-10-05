"""실제 장비 자료가 아닌, 재현 가능한 바이너리 STDF 데모 입력."""

from pathlib import Path
import random
import struct
from CODE_Common.io import write_json, digest


def generate(folder, *, parts=96, tests=500):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "DEMO_LOT001_W01.stdf"
    if source.exists():
        return source
    randomizer = random.Random(20261005)

    def cn(text):
        data = text.encode("ascii")
        return bytes([len(data)]) + data

    def rec(f, typ, sub, data):
        f.write(struct.pack("<HBB", len(data), typ, sub) + data)

    passed = 0
    with source.open("wb") as f:
        rec(f, 0, 10, bytes([2, 4]))
        mir = struct.pack(
            "<IIBcccHc", 1791158400, 1791158400, 1, b"P", b" ", b" ", 0, b" "
        )
        mir += b"".join(
            cn(x)
            for x in [
                "DEMO_LOT001",
                "DEMO_DUT",
                "ATE_DEMO",
                "DEMO_TESTER",
                "DEMO_PGM_A",
                "V1.0",
                "SUB01",
            ]
        )
        rec(f, 1, 10, mir)
        for bin_no, flag, name in [(1, b"P", "PASS"), (2, b"F", "FAIL")]:
            rec(f, 1, 50, struct.pack("<BBHIc", 1, 255, bin_no, 0, flag) + cn(name))
            rec(f, 1, 40, struct.pack("<BBHIc", 1, 255, bin_no, 0, flag) + cn(name))
        for p in range(parts):
            site = p % 4 + 1
            ok = p % 11 != 0
            passed += ok
            rec(f, 5, 10, bytes([1, site]))
            for t in range(tests):
                number = 99999 if t == tests - 1 else 100 + t * 137
                value = randomizer.gauss(1 + t / 200, 0.025)
                if not ok and t == 0:
                    value = 1.25
                ptr = struct.pack(
                    "<IBBBBf", number, 1, site, 0 if ok or t else 0x80, 0, value
                )
                ptr += cn(f"TEST_{number}") + cn("")
                ptr += struct.pack(
                    "<Bbbbff", 0, 0, 0, 0, 0.9 + t / 200, 1.1 + t / 200
                ) + cn("V")
                rec(f, 15, 10, ptr)
            b = 1 if ok else 2
            prr = struct.pack(
                "<BBBHHHhhI", 1, site, 0 if ok else 8, tests, b, b, p % 12, p // 12, 650
            )
            rec(f, 5, 20, prr + cn(f"DIE_{p:04}") + cn("") + bytes([0]))
    write_json(
        folder / "expected.json",
        {
            "synthetic": True,
            "parts": parts,
            "tests": tests,
            "pass": passed,
            "fail": parts - passed,
            "sha256": digest(source),
        },
    )
    return source


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="바이너리 STDF 샘플 생성")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    print(generate(args.output))
