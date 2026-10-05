"""Custom STDF V4 binary parser.

Implements the minimum decoder needed to produce the same Full CSV as the
legacy converter. Uses ``mmap`` + ``struct`` for zero-copy reads of the
selected record types: FAR, MIR, SDR, PMR, PIR, PRR, PTR, MPR, FTR. All other
record types are skipped via the ``REC_LEN`` header field.

The implementation prioritises speed: tight loops, cached ``struct.Struct``
instances, local-variable binding of hot helpers, and direct dict access.
"""
from __future__ import annotations

import mmap
import re
import struct
import time
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from .base import (
    ItemSpec, apply_scale, format_number, format_stdf_time, scale_label,
    passed_from_bins, truncation_warning,
    conversion_csv_paths,
    write_csv_outputs,
)

# Record header is always 4 bytes.
_HDR = struct.Struct("<HBB")  # little-endian default; rebuilt if big-endian.
_HDR_BE = struct.Struct(">HBB")

# Optional-field decoders are tiny helpers wrapping struct.Struct.
_LE = {
    "U1": struct.Struct("<B"),
    "U2": struct.Struct("<H"),
    "U4": struct.Struct("<I"),
    "I1": struct.Struct("<b"),
    "I2": struct.Struct("<h"),
    "I4": struct.Struct("<i"),
    "R4": struct.Struct("<f"),
    "R8": struct.Struct("<d"),
}
_BE = {
    "U1": struct.Struct(">B"),
    "U2": struct.Struct(">H"),
    "U4": struct.Struct(">I"),
    "I1": struct.Struct(">b"),
    "I2": struct.Struct(">h"),
    "I4": struct.Struct(">i"),
    "R4": struct.Struct(">f"),
    "R8": struct.Struct(">d"),
}


class _Reader:
    """Forward-only reader over a slice ``buf[start:end]`` (memoryview)."""

    __slots__ = ("buf", "pos", "end", "S", "_endian")

    def __init__(self, buf: memoryview, start: int, end: int, little: bool) -> None:
        self.buf = buf
        self.pos = start
        self.end = end
        self.S = _LE if little else _BE
        self._endian = "<" if little else ">"

    def remaining(self) -> int:
        return self.end - self.pos

    def u1(self) -> int | None:
        if self.pos + 1 > self.end:
            return None
        v = self.S["U1"].unpack_from(self.buf, self.pos)[0]
        self.pos += 1
        return v

    def u2(self) -> int | None:
        if self.pos + 2 > self.end:
            return None
        v = self.S["U2"].unpack_from(self.buf, self.pos)[0]
        self.pos += 2
        return v

    def u4(self) -> int | None:
        if self.pos + 4 > self.end:
            return None
        v = self.S["U4"].unpack_from(self.buf, self.pos)[0]
        self.pos += 4
        return v

    def i1(self) -> int | None:
        if self.pos + 1 > self.end:
            return None
        v = self.S["I1"].unpack_from(self.buf, self.pos)[0]
        self.pos += 1
        return v

    def i2(self) -> int | None:
        if self.pos + 2 > self.end:
            return None
        v = self.S["I2"].unpack_from(self.buf, self.pos)[0]
        self.pos += 2
        return v

    def r4(self) -> float | None:
        if self.pos + 4 > self.end:
            return None
        v = self.S["R4"].unpack_from(self.buf, self.pos)[0]
        self.pos += 4
        return v

    def cn(self) -> str:
        """Variable-length string. Format: U1 length + bytes (ASCII/latin-1)."""
        if self.pos + 1 > self.end:
            return ""
        n = self.buf[self.pos]
        self.pos += 1
        if n == 0:
            return ""
        end = self.pos + n
        if end > self.end:
            end = self.end
        s = bytes(self.buf[self.pos:end]).decode("latin-1", errors="replace")
        self.pos = end
        return s

    def bn(self) -> bytes:
        """Variable-length byte field; same length-prefix as Cn."""
        if self.pos + 1 > self.end:
            return b""
        n = self.buf[self.pos]
        self.pos += 1
        end = self.pos + n
        if end > self.end:
            end = self.end
        v = bytes(self.buf[self.pos:end])
        self.pos = end
        return v

    def skip(self, n: int) -> None:
        self.pos = min(self.end, self.pos + n)


def run(
    stdf_path: Path,
    out_dir: Path,
    progress_callback: Callable[[int, str], None] | None = None,
    *,
    write_full: bool = True,
    write_pass: bool = False,
    write_ng: bool = False,
    ptr_decoder: Callable[..., None] | None = None,
) -> dict[str, Any]:
    decode_ptr = ptr_decoder or _decode_ptr
    out_dir.mkdir(parents=True, exist_ok=True)
    if not (write_full or write_pass or write_ng):
        write_full = True
    paths = conversion_csv_paths(
        stdf_path,
        write_full=write_full,
        write_pass=write_pass,
        write_ng=write_ng,
        out_dir=out_dir,
    )
    full_path = paths["full"]
    pass_path = paths["pass"]
    ng_path = paths["ng"]

    started = time.perf_counter()

    metadata: dict[str, str] = {}
    pmr_names: dict[int, str] = {}
    items: "OrderedDict[tuple[int, str], ItemSpec]" = OrderedDict()
    current_parts: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    # testnum -> list[(key, res_scale)] cached from the first MPR for that test.
    # Subsequent MPRs reuse this so all sites land in the same columns.
    mpr_pin_specs: dict[int, list[tuple[tuple[int, str], int | None]]] = {}
    ftr_name_cache: dict[int, tuple[int, str]] = {}
    sbin_names: dict[int, str] = {}
    hbin_names: dict[int, str] = {}
    sbin_pf: dict[int, str] = {}
    hbin_pf: dict[int, str] = {}
    src_name = stdf_path.name
    file_size = stdf_path.stat().st_size
    last_progress = 5

    if file_size == 0:
        raise ValueError(f"Empty STDF file: {stdf_path.name}")
    from ..row_spool import RowSpool, should_spool
    if should_spool(stdf_path):
        rows = RowSpool()  # type: ignore[assignment]
    ptr_name_cache: dict[int, tuple[int, str]] = {}
    warnings: list[str] = []

    with open(stdf_path, "rb") as fp:
        # mmap the whole file (read-only). For very large files mmap is still
        # fine on 64-bit Python.
        mm = mmap.mmap(fp.fileno(), 0, access=mmap.ACCESS_READ)
        buf = memoryview(mm)
        try:
            little = _detect_endian(buf)
            hdr_struct = _HDR if little else _HDR_BE

            pos = 0
            end = len(buf)
            unpack_hdr = hdr_struct.unpack_from
            S = _LE if little else _BE

            while pos + 4 <= end:
                rec_len, rec_typ, rec_sub = unpack_hdr(buf, pos)
                body_start = pos + 4
                body_end = body_start + rec_len
                if body_end > end:
                    warnings.append(truncation_warning(pos, rec_typ, rec_sub))
                    break

                # Emit progress every ~256 KB. Parse phase is mapped to 5%-60%
                # to leave headroom for CSV write phase (60%-98%).
                if progress_callback and (pos & 0x3FFFF) == 0:
                    pct = min(60, max(last_progress, 5 + int(pos / file_size * 55)))
                    if pct > last_progress:
                        last_progress = pct
                        progress_callback(pct, f"Binary parse @ {pos // 1024:,} KB")

                # Dispatch only the record types we need.
                key = (rec_typ, rec_sub)
                if key == (15, 10):  # PTR
                    decode_ptr(buf, body_start, body_end, S, current_parts, items, src_name, ptr_name_cache)
                elif key == (5, 20):  # PRR
                    _decode_prr(buf, body_start, body_end, S, current_parts, rows, src_name)
                elif key == (5, 10):  # PIR
                    _decode_pir(buf, body_start, body_end, S, current_parts, src_name)
                elif key == (15, 15):  # MPR
                    _decode_mpr(buf, body_start, body_end, S, little, current_parts, items, pmr_names, mpr_pin_specs, src_name)
                elif key == (15, 20):  # FTR
                    _decode_ftr(buf, body_start, body_end, S, current_parts, items, ftr_name_cache, src_name)
                elif key == (1, 60):  # PMR
                    _decode_pmr(buf, body_start, body_end, little, pmr_names)
                elif key == (1, 10):  # MIR
                    _decode_mir(buf, body_start, body_end, S, little, metadata)
                elif key == (1, 80):  # SDR
                    _decode_sdr(buf, body_start, body_end, little, metadata)
                elif key == (1, 40):  # HBR
                    _decode_bin(buf, body_start, body_end, little, hbin_names, hbin_pf)
                elif key == (1, 50):  # SBR
                    _decode_bin(buf, body_start, body_end, little, sbin_names, sbin_pf)
                # else: skip silently.

                pos = body_end
            else:
                if pos != end:
                    warnings.append(f"Trailing {end - pos} bytes after final STDF record")
        finally:
            buf.release()
            mm.close()
    if current_parts:
        warnings.append(f"{len(current_parts)} DUT(s) opened by PIR without PRR were ignored")

    parse_elapsed = time.perf_counter() - started

    def passed(part):
        return passed_from_bins(part.get("soft_bin"), part.get("hard_bin"), sbin_pf, hbin_pf)

    bin_stats = _compute_bin_stats(rows, sbin_names, hbin_names, sbin_pf, hbin_pf)

    if progress_callback:
        progress_callback(62, f"Binary: writing CSV ({len(rows):,} rows)")

    full_count, pass_count, ng_count = write_csv_outputs(
        stdf_path, metadata, items, rows,
        full_path=full_path, pass_path=pass_path, ng_path=ng_path,
        progress_callback=progress_callback,
        progress_range=(62, 96),
        marker_values={
            "BIN_STATS_JSON": bin_stats,
            "ITEMS": len(items),
        },
        pass_rule=passed,
    )
    total_elapsed = time.perf_counter() - started

    csv_bytes = 0
    for p in (full_path, pass_path, ng_path):
        if p is not None and p.exists():
            csv_bytes += p.stat().st_size

    total_rows = len(rows)
    stats_pass = bin_stats["pass"]
    stats_ng = total_rows - stats_pass
    if isinstance(rows, RowSpool):
        rows.close()

    return {
        "parser": "binary",
        "output_dir": str(out_dir),
        "full_csv": str(full_path) if full_path else "",
        "pass_csv": str(pass_path) if pass_path else "",
        "ng_csv": str(ng_path) if ng_path else "",
        "rows": total_rows,
        "pass_rows": stats_pass,
        "ng_rows": stats_ng,
        "written_pass_rows": pass_count,
        "written_ng_rows": ng_count,
        "items": len(items),
        "elapsed_ms": int(total_elapsed * 1000),
        "parse_elapsed_ms": int(parse_elapsed * 1000),
        "csv_bytes": csv_bytes,
        "stdf_bytes": file_size,
        "throughput_mb_s": (file_size / (1024 * 1024)) / total_elapsed if total_elapsed > 0 else 0.0,
        "bin_stats": bin_stats,
        "metadata": dict(metadata),
        "warnings": warnings,
    }


def _compute_bin_stats(rows, sbin_names, hbin_names, sbin_pf, hbin_pf):
    """Aggregate HBIN/SBIN counts from parsed PRR rows.

    Returns a dict shaped for the UI:
        {
            "total": int, "pass": int, "fail": int, "yield_pct": float,
            "hbin": [{"num": int, "name": str, "pf": str, "count": int, "pct": float}, ...],
            "sbin": [{"num": int, "name": str, "pf": str, "count": int, "pct": float}, ...],
        }
    Pass follows SBR/HBR BIN_PF flags, falling back to SBIN==1 (or HBIN==1
    when SBIN is missing) — the same rule as the analysis path.
    """
    from collections import Counter
    hcnt: Counter = Counter()
    scnt: Counter = Counter()
    pass_n = 0
    for part in rows:
        sb_raw = str(part.get("soft_bin", "") or "")
        hb_raw = str(part.get("hard_bin", "") or "")
        sb = _to_int_or_none(sb_raw)
        hb = _to_int_or_none(hb_raw)
        if sb is not None:
            scnt[sb] += 1
        if hb is not None:
            hcnt[hb] += 1
        is_pass = passed_from_bins(sb, hb, sbin_pf, hbin_pf)
        if is_pass:
            pass_n += 1
    total = len(rows)
    fail = total - pass_n
    yld = (pass_n / total * 100.0) if total else 0.0

    def make(num, count, names, pf_map):
        name = names.get(num, "")
        if num == 1 and not name:
            name = "PASS"
        return {
            "num": num,
            "name": name,
            "pf": pf_map.get(num, ""),
            "count": count,
            "pct": (count / total * 100.0) if total else 0.0,
        }

    hbin_list = [make(num, cnt, hbin_names, hbin_pf) for num, cnt in sorted(hcnt.items())]
    sbin_list = [make(num, cnt, sbin_names, sbin_pf) for num, cnt in sorted(scnt.items())]
    return {
        "total": total,
        "pass": pass_n,
        "fail": fail,
        "yield_pct": yld,
        "hbin": hbin_list,
        "sbin": sbin_list,
    }


def _to_int_or_none(s: str) -> int | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Endian detection
# ---------------------------------------------------------------------------

def _detect_endian(buf: memoryview) -> bool:
    """Return True if file is little-endian. Determined from FAR (1,10)... wait,
    FAR is (0,10). FAR body starts with CPU_TYPE(U1) STDF_VER(U1).
    CPU_TYPE: 1=Sun(BE), 2=PC(LE), 3=other (treat as BE)."""
    if len(buf) < 6:
        return True
    # We try little first to read the header.
    rec_len_le, rec_typ, rec_sub = _HDR.unpack_from(buf, 0)
    if rec_typ == 0 and rec_sub == 10 and 2 <= rec_len_le <= 16:
        cpu_type = buf[4]
        return cpu_type == 2
    rec_len_be, rec_typ, rec_sub = _HDR_BE.unpack_from(buf, 0)
    if rec_typ == 0 and rec_sub == 10 and 2 <= rec_len_be <= 16:
        cpu_type = buf[4]
        return cpu_type == 2
    return True


# ---------------------------------------------------------------------------
# Per-record decoders. Inlined for speed; all hot paths avoid object creation
# where possible.
# ---------------------------------------------------------------------------

def _new_part(src_name: str, site: str) -> dict[str, Any]:
    return {
        "part_id": "", "temp": "", "x_coord": "", "y_coord": "",
        "wafer_id": "", "soft_bin": "", "hard_bin": "", "test_time": "",
        "shot_id": "", "site": site, "source_dataset": src_name, "plot_ul": "",
        "values": {},
    }


@lru_cache(maxsize=4096)
def _is_time_now_test(name: str) -> bool:
    norm = "".join(c.lower() for c in (name or "") if c.isalnum())
    return norm in ("timenow", "realtime") or "timenow" in norm


def _time_now_hhmmss(value: Any) -> str:
    """Map Time_now measurement to HHMMSS text stored in CSV ``temp`` column."""
    text = str(value or "").strip()
    if not text:
        return ""
    m = re.match(r"^(\d{1,2}):(\d{2})[:\s](\d{2})$", text)
    if m:
        return f"{int(m.group(1)):02d}{m.group(2)}{m.group(3)}"
    if re.fullmatch(r"\d{1,6}", text):
        return text
    try:
        iv = int(float(text))
    except ValueError:
        return ""
    if 0 <= iv < 1_000_000:
        s = str(iv)
        return s.zfill(6) if len(s) <= 6 else s[-6:]
    return ""


def _decode_mir(buf, start, end, S, little, metadata):
    r = _Reader(buf, start, end, little)
    # SETUP_T U4, START_T U4, STAT_NUM U1, MODE_COD/RTST_COD/PROT_COD C1,
    # BURN_TIM U2, CMOD_COD C1, then a long sequence of Cn fields.
    r.u4()  # SETUP_T
    start_t = r.u4() or 0
    r.skip(1)  # STAT_NUM
    r.skip(3)  # MODE_COD, RTST_COD, PROT_COD (C1)
    r.u2()  # BURN_TIM
    r.skip(1)  # CMOD_COD
    lot_id = r.cn()
    r.cn()  # PART_TYP
    node_nam = r.cn()
    tstr_typ = r.cn()
    job_nam = r.cn()
    job_rev = r.cn()
    sblot_id = r.cn()
    metadata.update({
        "lotid": lot_id,
        "sublotid": sblot_id,
        "start_t": format_stdf_time(start_t),
        "program": job_nam,
        "tester_type": tstr_typ,
        "tester_id": node_nam,
        "handler": metadata.get("handler", ""),
        "finish_t": "",
        "job_rev": job_rev,
    })


def _decode_sdr(buf, start, end, little, metadata):
    r = _Reader(buf, start, end, little)
    r.u1()  # HEAD_NUM
    r.u1()  # SITE_GRP
    site_cnt = r.u1() or 0
    r.skip(site_cnt)  # SITE_NUM array (U1 each)
    hand_typ = r.cn()
    hand_id = r.cn()
    handler = hand_id or hand_typ
    if handler:
        metadata["handler"] = handler


def _decode_bin(buf, start, end, little, names, pf_map):
    """Shared decoder for HBR (1,40) and SBR (1,50)."""
    r = _Reader(buf, start, end, little)
    r.u1()  # HEAD_NUM
    r.u1()  # SITE_NUM
    bin_num = r.u2()
    r.u4()  # BIN_CNT
    pf = ""
    if r.remaining() > 0:
        b = r.u1()
        if b is not None and 32 <= b < 127:
            pf = chr(b)
    name = r.cn() if r.remaining() > 0 else ""
    if bin_num is None:
        return
    # Multiple records per (head,site) — last non-empty name wins.
    if name:
        names[bin_num] = name
    if pf and bin_num not in pf_map:
        pf_map[bin_num] = pf


def _decode_pmr(buf, start, end, little, pmr_names):
    r = _Reader(buf, start, end, little)
    pmr_indx = r.u2()
    r.u2()  # CHAN_TYP
    chan_nam = r.cn()
    phy_nam = r.cn()
    r.cn()  # LOG_NAM
    if pmr_indx is not None:
        pmr_names[pmr_indx] = chan_nam or phy_nam or str(pmr_indx)


def part_key(head: int | None, site: int | None) -> str:
    """Active-DUT key. HEAD_NUM and SITE_NUM together identify one test slot;
    keying by SITE alone merges DUTs from different heads."""
    return f"{'' if head is None else head}:{'' if site is None else site}"


def _decode_pir(buf, start, end, S, current_parts, src_name):
    """Open a DUT slot and return its active-part key (None if malformed)."""
    # HEAD_NUM U1, SITE_NUM U1
    if end - start < 2:
        return None
    head = buf[start]
    site = str(buf[start + 1])
    key = part_key(head, buf[start + 1])
    part = _new_part(src_name, site)
    part["head"] = str(head)
    current_parts[key] = part
    return key


def _active_part(current_parts, head, site_num, src_name):
    key = part_key(head, site_num)
    part = current_parts.get(key)
    if part is None:
        part = _new_part(src_name, "" if site_num is None else str(site_num))
        part["head"] = "" if head is None else str(head)
        current_parts[key] = part
    return part


def _is_little(S) -> bool:
    """Identify the little-endian table without relying on object identity.

    struct.Struct compares by identity on current CPythons, so a rebuilt
    table of equal-format structs must be recognised via format strings;
    "<H" is little-endian by definition, so it is a safe probe.
    """
    if S is _LE or S == _LE:
        return True
    probe = S.get("U2") if hasattr(S, "get") else None
    return probe is not None and probe.format == _LE["U2"].format


def _decode_prr(buf, start, end, S, current_parts, rows, src_name):
    r = _Reader(buf, start, end, _is_little(S))
    head = r.u1()  # HEAD_NUM
    site_num = r.u1()
    site = str(site_num) if site_num is not None else ""
    r.skip(1)  # PART_FLG
    r.u2()    # NUM_TEST
    hard_bin = r.u2()
    soft_bin = r.u2()
    x_coord = r.i2()
    y_coord = r.i2()
    test_t = r.u4()
    part_id = r.cn()
    part = current_parts.pop(part_key(head, site_num), None) or _new_part(src_name, site)
    part["head"] = "" if head is None else str(head)
    part["part_id"] = part_id
    part["soft_bin"] = "" if soft_bin is None else str(soft_bin)
    part["hard_bin"] = "" if hard_bin is None else str(hard_bin)
    part["x_coord"] = "" if x_coord is None else str(x_coord)
    part["y_coord"] = "" if y_coord is None else str(y_coord)
    part["test_time"] = "" if test_t is None else str(test_t)
    part["site"] = site
    part["source_dataset"] = src_name
    rows.append(part)


def _decode_ptr(buf, start, end, S, current_parts, items, src_name, ptr_name_cache=None,
                capture_later_metadata=True):
    r = _Reader(buf, start, end, _is_little(S))
    testnum = r.u4() or 0
    head = r.u1()  # HEAD_NUM
    site_num = r.u1()
    test_flg = r.u1() or 0
    parm_flg = r.u1() or 0
    _ = parm_flg
    result = r.r4()
    test_txt = r.cn()
    r.cn()  # ALARM_ID

    # STDF lets later PTRs omit TEST_TXT (defaults come from the first PTR).
    # Reuse the first name for that test number instead of opening a separate
    # "TEST_<n>" column; distinct non-empty names still stay separate items.
    if test_txt:
        key = (testnum, test_txt)
        if ptr_name_cache is not None:
            ptr_name_cache.setdefault(testnum, key)
    else:
        key = (ptr_name_cache or {}).get(testnum) or (testnum, f"TEST_{testnum}")
    name = key[1]

    # OPT_FLAG and following are present only if data remains. The first time
    # we meet an item we capture its scaling/limits; thereafter we just use
    # the cached spec scale.
    spec = items.get(key)
    res_scale: int | None = None
    if spec is None:
        units = ""
        ll_value: float | None = None
        ul_value: float | None = None
        llm_scal: int | None = None
        hlm_scal: int | None = None
        opt_flag = 0xFF
        optional_captured = r.remaining() > 0
        if optional_captured:
            opt_flag = r.u1() or 0
            res_scale = r.i1()
            llm_scal = r.i1()
            hlm_scal = r.i1()
            ll_value = r.r4()
            ul_value = r.r4()
            units = r.cn()
            if opt_flag & 0x01:  # bit0: RES_SCAL invalid
                res_scale = None
        # Decide validity from OPT_FLAG bits.
        # bit0 (0x01): RES_SCAL invalid
        # bit2 (0x04): LO_SPEC invalid
        # bit3 (0x08): HI_SPEC invalid
        # bit4 (0x10): LO_LIMIT invalid (use default)
        # bit5 (0x20): HI_LIMIT invalid (use default)
        # bit6 (0x40): no LO_LIMIT for this test
        # bit7 (0x80): no HI_LIMIT for this test
        scaler = scale_label(res_scale or 0)
        ll_text = ""
        ul_text = ""
        if ll_value is not None and not (opt_flag & 0x50):
            ll_text = format_number(apply_scale(ll_value, llm_scal))
        if ul_value is not None and not (opt_flag & 0xA0):
            ul_text = format_number(apply_scale(ul_value, hlm_scal))
        spec = ItemSpec(testnum=testnum, name=name, scaler=scaler, units=units,
                        ll=ll_text, ul=ul_text, record_type="PTR")
        items[key] = spec
        # Cache scale on spec for reuse below.
        spec._res_scale = res_scale  # type: ignore[attr-defined]
        spec._meta_optional_captured = optional_captured
        spec._meta_res_scale = res_scale
        spec._meta_low = None if ll_value is None or opt_flag & 0x50 else apply_scale(ll_value, llm_scal)
        spec._meta_high = None if ul_value is None or opt_flag & 0xA0 else apply_scale(ul_value, hlm_scal)
        spec._meta_units = units
    else:
        res_scale = getattr(spec, "_res_scale", None)
        # The first PTR can omit optional metadata. Capture the first later
        # optional block, and preserve the legacy preference for the first
        # block that supplies a valid low limit. Result scaling continues to
        # use the original cached scale so measurement values remain exact.
        # V93K keeps its legacy first-PTR-only metadata (capture_later_metadata=False).
        if (capture_later_metadata
                and (not spec._meta_optional_captured or spec._meta_low is None)
                and r.remaining() > 0):
            opt_flag = r.u1() or 0
            meta_res_scale = r.i1()
            if opt_flag & 0x01:
                meta_res_scale = None
            llm_scal = r.i1()
            hlm_scal = r.i1()
            ll_value = r.r4()
            ul_value = r.r4()
            units = r.cn()
            meta_low = None if ll_value is None or opt_flag & 0x50 else apply_scale(ll_value, llm_scal)
            meta_high = None if ul_value is None or opt_flag & 0xA0 else apply_scale(ul_value, hlm_scal)
            if not spec._meta_optional_captured or (spec._meta_low is None and meta_low is not None):
                spec._meta_optional_captured = True
                spec._meta_res_scale = meta_res_scale
                spec._meta_low = meta_low
                spec._meta_high = meta_high
                spec._meta_units = units
                if not spec.scaler:
                    spec.scaler = scale_label(meta_res_scale or 0)
                if not spec.units:
                    spec.units = units
                if not spec.ll and meta_low is not None:
                    spec.ll = format_number(meta_low)
                if not spec.ul and meta_high is not None:
                    spec.ul = format_number(meta_high)

    # bit1 (0x02): result invalid, bit4 (0x10): no result present. Other bits
    # (including pass/fail bit 7) do not imply the measured value is missing,
    # so we keep results for failed parts too — matching the reference tool.
    if result is not None and (test_flg & 0x12) == 0:
        scaled = apply_scale(result, res_scale)
        part = _active_part(current_parts, head, site_num, src_name)
        part["values"][key] = format_number(scaled)
        if _is_time_now_test(name):
            clock = _time_now_hhmmss(scaled if scaled is not None else result)
            if clock:
                part["temp"] = clock


def _decode_mpr(buf, start, end, S, little, current_parts, items, pmr_names, mpr_pin_specs, src_name):
    r = _Reader(buf, start, end, little)
    testnum = r.u4() or 0
    head = r.u1()
    site_num = r.u1()
    test_flg = r.u1() or 0  # TEST_FLG
    r.u1()  # PARM_FLG
    # Same rule as PTR: bit1 (result invalid) / bit4 (not executed) mean the
    # RTN_RSLT array must not be used as measurements.
    results_valid = (test_flg & 0x12) == 0
    rtn_icnt = r.u2() or 0
    rslt_cnt = r.u2() or 0
    # RTN_STAT: jxN1 nibble-packed: ceil(j/2) bytes.
    r.skip((rtn_icnt + 1) // 2)
    # RTN_RSLT: kxR4
    if r.pos + rslt_cnt * 4 > end:
        return
    if rslt_cnt:
        fmt = ("<" if little else ">") + f"{rslt_cnt}f"
        results = struct.unpack_from(fmt, buf, r.pos)
        r.skip(rslt_cnt * 4)
    else:
        results = ()
    test_txt = r.cn()
    r.cn()  # ALARM_ID

    part = _active_part(current_parts, head, site_num, src_name)

    # Subsequent MPRs for the same testnum typically omit the optional
    # metadata block (RTN_INDX, UNITS, scales). Without caching we would
    # build new "/1", "/2"... fallback names and split the same test across
    # two column groups. Reuse the first MPR's pin mapping verbatim.
    cached = mpr_pin_specs.get(testnum)
    if cached:
        if len(results) > len(cached):
            # A later MPR can return more pins than the first one. Extend the
            # mapping from the first pin's spec instead of dropping values.
            first_key, first_scale = cached[0]
            first_spec = items[first_key]
            base_name = first_key[1].rsplit("/", 1)[0]
            for i in range(len(cached), len(results)):
                key = (testnum, f"{base_name}/{i + 1}")
                if key not in items:
                    spec = ItemSpec(testnum=testnum, name=key[1], scaler=first_spec.scaler,
                                    units=first_spec.units, ll=first_spec.ll, ul=first_spec.ul,
                                    record_type="MPR")
                    spec._res_scale = first_scale  # type: ignore[attr-defined]
                    items[key] = spec
                cached.append((key, first_scale))
        if not results_valid:
            return
        for i, value in enumerate(results):
            key, res_scale_cached = cached[i]
            scaled = apply_scale(value, res_scale_cached)
            part["values"][key] = format_number(scaled)
        return

    base_name = test_txt or f"TEST_{testnum}"
    res_scale: int | None = None
    llm_scal: int | None = None
    hlm_scal: int | None = None
    ll_value: float | None = None
    ul_value: float | None = None
    units = ""
    indexes: tuple[int, ...] = ()
    opt_flag = 0xFF
    if r.remaining() > 0:
        opt_flag = r.u1() or 0
        res_scale = r.i1()
        if opt_flag & 0x01:  # bit0: RES_SCAL invalid
            res_scale = None
        llm_scal = r.i1()
        hlm_scal = r.i1()
        ll_value = r.r4()
        ul_value = r.r4()
        r.r4()  # START_IN
        r.r4()  # INCR_IN
        if rtn_icnt and r.pos + rtn_icnt * 2 <= end:
            fmt = ("<" if little else ">") + f"{rtn_icnt}H"
            indexes = struct.unpack_from(fmt, buf, r.pos)
            r.skip(rtn_icnt * 2)
        units = r.cn()

    scaler = scale_label(res_scale or 0)
    ll_text = ""
    ul_text = ""
    if ll_value is not None and not (opt_flag & 0x50):
        ll_text = format_number(apply_scale(ll_value, llm_scal))
    if ul_value is not None and not (opt_flag & 0xA0):
        ul_text = format_number(apply_scale(ul_value, hlm_scal))

    cache_entry: list[tuple[tuple[int, str], int | None]] = []
    for i, value in enumerate(results):
        pin = pmr_names.get(indexes[i], str(i + 1)) if i < len(indexes) else str(i + 1)
        name = f"{base_name}/{pin}"
        key = (testnum, name)
        spec = items.get(key)
        if spec is None:
            spec = ItemSpec(testnum=testnum, name=name, scaler=scaler, units=units,
                            ll=ll_text, ul=ul_text, record_type="MPR")
            spec._res_scale = res_scale  # type: ignore[attr-defined]
            items[key] = spec
        if results_valid:
            scaled = apply_scale(value, res_scale)
            part["values"][key] = format_number(scaled)
        cache_entry.append((key, res_scale))
    mpr_pin_specs[testnum] = cache_entry


def _decode_ftr(buf, start, end, S, current_parts, items, ftr_name_cache, src_name):
    r = _Reader(buf, start, end, _is_little(S))
    testnum = r.u4() or 0
    head = r.u1()  # HEAD_NUM
    site_num = r.u1()
    test_flg = r.u1() or 0
    opt_flag = r.u1() or 0

    part = _active_part(current_parts, head, site_num, src_name)

    # Once we know the proper TEST_TXT for this testnum, future FTRs for the
    # same testnum simply reuse the cached (key, spec) — much faster and
    # avoids parsing the heavy optional area again.
    cached_key = ftr_name_cache.get(testnum)
    if cached_key is not None:
        part["values"][cached_key] = str(test_flg)
        return

    # FTR fixed body: these fields are ALWAYS present in the record body.
    # OPT_FLAG only marks them as semantically invalid, not absent.
    r.skip(4)   # CYCL_NUM U4
    r.skip(4)   # REL_VADR U4
    r.skip(4)   # REPT_CNT U4
    r.skip(4)   # NUM_FAIL U4
    r.skip(4)   # XFAIL_AD I4
    r.skip(4)   # YFAIL_AD I4
    r.skip(2)   # VECT_OFF I2
    _ = opt_flag  # consumed for completeness

    rtn_icnt = r.u2() or 0
    pgm_icnt = r.u2() or 0
    r.skip(rtn_icnt * 2)         # RTN_INDX jxU2
    r.skip((rtn_icnt + 1) // 2)  # RTN_STAT jxN1
    r.skip(pgm_icnt * 2)         # PGM_INDX kxU2
    r.skip((pgm_icnt + 1) // 2)  # PGM_STAT kxN1

    # FAIL_PIN Dn: U2 bit length + ceil(bits/8) bytes.
    if r.remaining() >= 2:
        n_bits = S["U2"].unpack_from(r.buf, r.pos)[0]
        r.pos += 2
        r.skip((n_bits + 7) // 8)

    # Trailing Cn fields, all optional. Each missing field truncates the rest.
    if r.remaining() > 0:
        r.cn()  # VECT_NAM
    if r.remaining() > 0:
        r.cn()  # TIME_SET
    if r.remaining() > 0:
        r.cn()  # OP_CODE
    test_txt = r.cn() if r.remaining() > 0 else ""

    name = test_txt or f"TEST_{testnum}"
    key = (testnum, name)
    if key not in items:
        items[key] = ItemSpec(testnum=testnum, name=name, units="", record_type="FTR")
    ftr_name_cache[testnum] = key
    part["values"][key] = str(test_flg)
