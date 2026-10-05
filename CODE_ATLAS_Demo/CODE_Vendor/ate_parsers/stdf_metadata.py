from __future__ import annotations

from collections import Counter
from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.hex().upper()
    if isinstance(value, (list, tuple)):
        return "|".join(_text(item) for item in value)
    return str(value)


def _character(value: int | None) -> str:
    if value is None or value == 0:
        return ""
    return chr(value) if 32 <= value < 127 else str(value)


def _clean(value: Any) -> str:
    return _text(value).strip()


class StdfMetadataCollector:
    """Decode STDF V4 information records without changing test calculations."""

    def __init__(self, binary_parser, little: bool) -> None:
        self._bp = binary_parser
        self._little = little
        self._occurrences: Counter[str] = Counter()
        self.fields: dict[str, str] = {}
        self.canonical: dict[str, str] = {}

    def _reader(self, buf, start: int, end: int):
        return self._bp._Reader(buf, start, end, self._little)

    def _store(self, record: str, values: list[tuple[str, Any]]) -> None:
        self._occurrences[record] += 1
        occurrence = self._occurrences[record]
        prefix = f"STDF.{record}[{occurrence}]"
        for name, value in values:
            self.fields[f"{prefix}.{name}"] = _text(value)

    def collect(self, key: tuple[int, int], buf, start: int, end: int) -> None:
        decoder = {
            (0, 10): self._far,
            (0, 20): self._atr,
            (1, 10): self._mir,
            (1, 20): self._mrr,
            (1, 30): self._pcr,
            (1, 40): lambda *args: self._bin("HBR", *args),
            (1, 50): lambda *args: self._bin("SBR", *args),
            (1, 60): self._pmr,
            (1, 80): self._sdr,
            (2, 10): self._wir,
            (2, 20): self._wrr,
            (2, 30): self._wcr,
        }.get(key)
        if decoder is not None:
            decoder(buf, start, end)

    def add_record_counts(self, counts: dict[str, int]) -> None:
        for record, count in counts.items():
            self.fields[f"STDF.RECORD_COUNT.{record}"] = str(count)

    def _far(self, buf, start: int, end: int) -> None:
        r = self._reader(buf, start, end)
        self._store("FAR", [("CPU_TYPE", r.u1()), ("STDF_VER", r.u1())])

    def _atr(self, buf, start: int, end: int) -> None:
        r = self._reader(buf, start, end)
        modified = r.u4()
        self._store("ATR", [
            ("MOD_TIM", self._bp.format_stdf_time(modified)),
            ("CMD_LINE", r.cn()),
        ])

    def _mir(self, buf, start: int, end: int) -> None:
        r = self._reader(buf, start, end)
        setup_t = r.u4()
        start_t = r.u4()
        stat_num = r.u1()
        values: list[tuple[str, Any]] = [
            ("SETUP_T", self._bp.format_stdf_time(setup_t)),
            ("START_T", self._bp.format_stdf_time(start_t)),
            ("STAT_NUM", stat_num),
            ("MODE_COD", _character(r.u1())),
            ("RTST_COD", _character(r.u1())),
            ("PROT_COD", _character(r.u1())),
            ("BURN_TIM", r.u2()),
            ("CMOD_COD", _character(r.u1())),
        ]
        names = (
            "LOT_ID", "PART_TYP", "NODE_NAM", "TSTR_TYP", "JOB_NAM", "JOB_REV",
            "SBLOT_ID", "OPER_NAM", "EXEC_TYP", "EXEC_VER", "TEST_COD", "TST_TEMP",
            "USER_TXT", "AUX_FILE", "PKG_TYP", "FAMLY_ID", "DATE_COD", "FACIL_ID",
            "FLOOR_ID", "PROC_ID", "OPER_FRQ", "SPEC_NAM", "SPEC_VER", "FLOW_ID",
            "SETUP_ID", "DSGN_REV", "ENG_ID", "ROM_COD", "SERL_NUM", "SUPR_NAM",
        )
        decoded = {name: r.cn() for name in names}
        values.extend(decoded.items())
        self._store("MIR", values)
        self.canonical.update({
            "setup_t": self._bp.format_stdf_time(setup_t),
            "start_t": self._bp.format_stdf_time(start_t),
            "stat_num": _text(stat_num),
            "station_number": _text(stat_num),
            "lotid": _clean(decoded["LOT_ID"]),
            "part_typ": _clean(decoded["PART_TYP"]),
            "device": _clean(decoded["PART_TYP"]),
            "node_nam": _clean(decoded["NODE_NAM"]),
            "tester_id": _clean(decoded["NODE_NAM"]),
            "tester_type": _clean(decoded["TSTR_TYP"]),
            "program": _clean(decoded["JOB_NAM"]),
            "job_rev": _clean(decoded["JOB_REV"]),
            "sublotid": _clean(decoded["SBLOT_ID"]),
            "operator": _clean(decoded["OPER_NAM"]),
            "temperature": _clean(decoded["TST_TEMP"]),
            "title": _clean(decoded["USER_TXT"]),
            "comment": _clean(decoded["USER_TXT"]),
        })

    def _mrr(self, buf, start: int, end: int) -> None:
        r = self._reader(buf, start, end)
        finish_t = self._bp.format_stdf_time(r.u4())
        self._store("MRR", [
            ("FINISH_T", finish_t),
            ("DISP_COD", _character(r.u1())),
            ("USR_DESC", r.cn()),
            ("EXC_DESC", r.cn()),
        ])
        if finish_t:
            self.canonical["finish_t"] = finish_t

    def _pcr(self, buf, start: int, end: int) -> None:
        r = self._reader(buf, start, end)
        self._store("PCR", [
            ("HEAD_NUM", r.u1()), ("SITE_NUM", r.u1()), ("PART_CNT", r.u4()),
            ("RTST_CNT", r.u4()), ("ABRT_CNT", r.u4()), ("GOOD_CNT", r.u4()),
            ("FUNC_CNT", r.u4()),
        ])

    def _bin(self, record: str, buf, start: int, end: int) -> None:
        r = self._reader(buf, start, end)
        self._store(record, [
            ("HEAD_NUM", r.u1()), ("SITE_NUM", r.u1()), ("BIN_NUM", r.u2()),
            ("BIN_CNT", r.u4()), ("BIN_PF", _character(r.u1())), ("BIN_NAM", r.cn()),
        ])

    def _pmr(self, buf, start: int, end: int) -> None:
        r = self._reader(buf, start, end)
        self._store("PMR", [
            ("PMR_INDX", r.u2()), ("CHAN_TYP", r.u2()), ("CHAN_NAM", r.cn()),
            ("PHY_NAM", r.cn()), ("LOG_NAM", r.cn()), ("HEAD_NUM", r.u1()),
            ("SITE_NUM", r.u1()),
        ])

    def _sdr(self, buf, start: int, end: int) -> None:
        r = self._reader(buf, start, end)
        head_num = r.u1()
        site_grp = r.u1()
        site_count = r.u1() or 0
        sites = [r.u1() for _ in range(site_count)]
        names = (
            "HAND_TYP", "HAND_ID", "CARD_TYP", "CARD_ID", "LOAD_TYP", "LOAD_ID",
            "DIB_TYP", "DIB_ID", "CABL_TYP", "CABL_ID", "CONT_TYP", "CONT_ID",
            "LASR_TYP", "LASR_ID", "EXTR_TYP", "EXTR_ID",
        )
        decoded = {name: r.cn() for name in names}
        self._store("SDR", [
            ("HEAD_NUM", head_num), ("SITE_GRP", site_grp), ("SITE_CNT", site_count),
            ("SITE_NUM", sites), *decoded.items(),
        ])
        handler = _clean(decoded["HAND_ID"] or decoded["HAND_TYP"])
        if handler:
            self.canonical["handler"] = handler
        self.canonical.update({
            "probe_card": _clean(decoded["CARD_ID"] or decoded["CARD_TYP"]),
            "dutif": _clean(decoded["DIB_ID"] or decoded["LOAD_ID"]),
        })

    def _wir(self, buf, start: int, end: int) -> None:
        r = self._reader(buf, start, end)
        head_num = r.u1()
        site_grp = r.u1()
        start_t = self._bp.format_stdf_time(r.u4())
        wafer_id = r.cn()
        self._store("WIR", [
            ("HEAD_NUM", head_num), ("SITE_GRP", site_grp),
            ("START_T", start_t), ("WAFER_ID", wafer_id),
        ])
        if start_t:
            self.canonical["start_t"] = start_t
        if wafer_id:
            self.canonical["wafer"] = _clean(wafer_id)
            self.canonical["wafer_id"] = _clean(wafer_id)

    def _wrr(self, buf, start: int, end: int) -> None:
        r = self._reader(buf, start, end)
        head_num = r.u1()
        site_grp = r.u1()
        finish_t = self._bp.format_stdf_time(r.u4())
        values: list[tuple[str, Any]] = [
            ("HEAD_NUM", head_num), ("SITE_GRP", site_grp), ("FINISH_T", finish_t),
            ("PART_CNT", r.u4()), ("RTST_CNT", r.u4()), ("ABRT_CNT", r.u4()),
            ("GOOD_CNT", r.u4()), ("FUNC_CNT", r.u4()),
        ]
        names = ("WAFER_ID", "FABWF_ID", "FRAME_ID", "MASK_ID", "USR_DESC", "EXC_DESC")
        decoded = {name: r.cn() for name in names}
        values.extend(decoded.items())
        self._store("WRR", values)
        if finish_t:
            self.canonical["finish_t"] = finish_t
        if decoded["WAFER_ID"]:
            self.canonical["wafer"] = _clean(decoded["WAFER_ID"])
            self.canonical["wafer_id"] = _clean(decoded["WAFER_ID"])

    def _wcr(self, buf, start: int, end: int) -> None:
        r = self._reader(buf, start, end)
        self._store("WCR", [
            ("WAFR_SIZ", r.r4()), ("DIE_HT", r.r4()), ("DIE_WID", r.r4()),
            ("WF_UNITS", r.u1()), ("WF_FLAT", _character(r.u1())),
            ("CENTER_X", r.i2()), ("CENTER_Y", r.i2()),
            ("POS_X", _character(r.u1())), ("POS_Y", _character(r.u1())),
        ])
