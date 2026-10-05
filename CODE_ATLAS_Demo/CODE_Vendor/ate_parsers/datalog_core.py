"""Streaming ADVANTEST DataLog decoding; no histogram or UI dependencies."""
import math
import re
from .units import UM, parse_val

_HM = {
    'plan': re.compile(r'Plan Name\s*:\s*(\S+)'), 'device': re.compile(r'Device Name\s*:\s*(\S+)'),
    'lot': re.compile(r'Lot #\s*:\s*(\S+)'), 'sublot': re.compile(r'Sub Lot #\s*:\s*(\S+)'),
    'wafer': re.compile(r'Wafer Name\s*:\s*(\S+)'), 'operator': re.compile(r'Operator\s*:\s*(\S+)'),
    'dutif': re.compile(r'DUT I/F\s*:\s*(\S+)'), 'station': re.compile(r'Station No\s*:\s*(\S+)'),
    'date': re.compile(r'ADVANTEST DataLog:\s*(.+)'), 'comment': re.compile(r'Comments\s*:\s*(.+)'),
}
_RE_T     = re.compile(r'\*{10,}\s+\[Test\s+(\d+)\]\s+(\w+)\s+(?:PASS|FAIL)\s+"([^"]+)"\s+\*{10,}')
_RE_DUTHDR= re.compile(r'DUT\s+X\s+Y')
_RE_DUTXY = re.compile(r'^\s+(\d+)\s+(-?\d+)\s+(-?\d+)\s*$')
_RE_SAM   = re.compile(r'Sample\s*#\s*:\s*(\S+)', re.I)
_RE_CAT   = re.compile(r'Category\s*:', re.I)
_RE_DUTCAT= re.compile(r'^DUT\s{1,5}:\s*(\d+)\s*$')
_RE_FTDUT = re.compile(r'^DUT\s+:\s*(\d+)\s*$')

def _new_item(key, tid, title, pin, ctype, bu, lo, up):
    return dict(key=key, tid=tid, title=title, pin=pin, dutNum=None, type=ctype, baseUnit=bu,
                data=[], _cnt=0, _sum=0.0, _sum2=0.0, _mn=math.inf, _mx=-math.inf, _lo=lo, _up=up, _ofc=0)

def parse_datalog(line_iter, cfg, allowed_tids=None, group_by_tid=False, on_progress=None):
    hdr = {k: '' for k in _HM}
    from .row_spool import RowSpool
    imap = {}; iord = []; chip_records = RowSpool() if cfg.get('_spool_rows') else []
    blk_sample = None; blk_coords = {}; blk_meas = {}; blk_cat = {}
    expect_xy = False; xy_buf = []; cat_dut = None
    ct = None; ctype = None; ctitle = None; in_d = False
    ft_block = False; ft_pending = None
    header_done = False    # 헤더필드는 첫 테스트 전(맨 위)에만 → 이후 HM 매칭 생략(속도)

    def flush_block():
        for dut, mm in blk_meas.items():
            if not mm: continue
            xy = blk_coords.get(dut, {'x': None, 'y': None})
            chip_records.append(dict(sample=blk_sample, dut=dut, x=xy['x'], y=xy['y'],
                                     category=blk_cat.get(dut, ''), sort=0, meas=dict(mm)))

    for raw in line_iter:
        line = raw.rstrip('\r\n')

        if not header_done:
            for k, rh in _HM.items():
                if not hdr[k]:
                    m = rh.search(line)
                    if m: hdr[k] = m.group(1).strip()

        if 'ADVANTEST DataLog:' in line:
            flush_block()
            blk_sample = None; blk_coords = {}; blk_meas = {}; blk_cat = {}
            expect_xy = False; xy_buf = []; cat_dut = None
            ct = None; ctype = None; ctitle = None; in_d = False; ft_block = False; ft_pending = None
            continue

        # ── 싼 in/startswith 가드로 정규식 호출 최소화 (데이터 라인은 모두 통과) ──
        if 'Sample' in line:
            m = _RE_SAM.search(line)
            if m:
                try: blk_sample = int(m.group(1))
                except ValueError: blk_sample = None
                continue

        if 'DUT' in line and _RE_DUTHDR.search(line):
            expect_xy = True; xy_buf = []; continue
        if expect_xy:
            mxy = _RE_DUTXY.match(line)
            if mxy:
                xy_buf.append((int(mxy.group(1)), int(mxy.group(2)), int(mxy.group(3)))); continue
            if line.strip() == '': continue
            expect_xy = False
            for d, x, y in xy_buf:
                blk_coords[d] = {'x': x, 'y': y}
                blk_meas.setdefault(d, {})
            xy_buf = []

        if line.startswith('DUT'):
            mdc = _RE_DUTCAT.match(line)
            if mdc:
                cat_dut = int(mdc.group(1)); continue
            # FT의 'DUT          : n'(공백 다수)는 아래 ft_block에서 처리

        if 'Category' in line and _RE_CAT.search(line):
            val = line.split(':', 1)[1].strip() if ':' in line else ''
            if cat_dut is not None: blk_cat[cat_dut] = val
            else:
                for d in list(blk_coords.keys()): blk_cat[d] = val
            continue

        if '[Test' in line:
            th = _RE_T.search(line)
            if th:
                ct = int(th.group(1)); ctype = th.group(2); ctitle = th.group(3); in_d = False; ft_pending = None
                header_done = True
                # FT 활성화: ASC모드면 등록 tid만, REAL모드면 Function(c.ft) ON일 때만
                if allowed_tids is not None:
                    if ct not in allowed_tids: ct = None
                elif ctype == 'FT' and not cfg.get('ft'):
                    ct = None
                ft_block = (ct is not None and ctype == 'FT')
                continue

        # ── FT(Function) 블록: DUT별 PASS=0 / NG=1 주입 ──
        if ft_block and ct is not None:
            mft = _RE_FTDUT.match(line)
            if mft:
                ft_pending = int(mft.group(1)); continue
            if ft_pending is not None:
                tl = line.strip()
                if tl != '':
                    is_pass = (tl == 'PASS'); si = 0 if is_pass else 1
                    hk = ('%d|' % ct) if group_by_tid else ('%d|%s|' % (ct, ctitle))
                    it = imap.get(hk)
                    if it is None:
                        it = _new_item(hk, ct, ctitle, '', 'FT', '', None, None)
                        imap[hk] = it; iord.append(hk)
                    if not cfg.get('_metadata_only') or not it['data']:
                        it['data'].append([si, is_pass, None, None, ''])
                    it['_cnt'] += 1; it['_sum'] += si; it['_sum2'] += si*si
                    if si < it['_mn']: it['_mn'] = si
                    if si > it['_mx']: it['_mx'] = si
                    blk_meas.setdefault(ft_pending, {})['%d|%s|' % (ct, ctitle)] = \
                        {'si': si, 'unit': '', 'pass': is_pass, 'lo': None, 'up': None}
                    ft_pending = None
            continue

        if ct is not None and 'TestID' in line and ('RESULT' in line or 'Value' in line):
            in_d = True; continue

        if in_d and ct is not None:
            p = parse_data_line(line)
            if not p or p['tid'] != ct: continue
            dut = p['dut']; pin_part = p['pin'] if cfg.get('pin') else ''
            pu = parse_val(p['up']); pl = parse_val(p['lo'])
            up2 = pu[0] if pu else None; lo2 = pl[0] if pl else None
            bu = ''
            if pu and pu[1] and pl and pl[1]:
                bu = pl[1] if (UM.get(pl[1],1) <= UM.get(pu[1],1)) else pu[1]
            elif pu and pu[1]: bu = pu[1]
            elif pl and pl[1]: bu = pl[1]
            hk = ('%d|%s' % (ct, pin_part)) if group_by_tid else ('%d|%s|%s' % (ct, ctitle, pin_part))
            it = imap.get(hk)
            if it is None:
                it = _new_item(hk, ct, ctitle, pin_part, ctype, bu, None, None)
                imap[hk] = it; iord.append(hk)
            pval = parse_val(p['val'])
            if not pval:
                if re.search(r'\*{3,}', p['val']): it['_ofc'] += 1
                continue
            si, raw_unit = pval
            if not it['baseUnit'] and raw_unit: it['baseUnit'] = raw_unit
            res_mk = p['result']
            if res_mk:
                ip = (res_mk == 'OVERFLOW')
            else:
                ip = (lo2 <= si <= up2) if (up2 is not None and lo2 is not None) else True
            if not cfg.get('_metadata_only') or not it['data']:
                it['data'].append([si, ip, up2, lo2, it['baseUnit']])
            it['_cnt'] += 1; it['_sum'] += si; it['_sum2'] += si*si
            if si < it['_mn']: it['_mn'] = si
            if si > it['_mx']: it['_mx'] = si
            if it['_lo'] is None and lo2 is not None: it['_lo'] = lo2
            if it['_up'] is None and up2 is not None: it['_up'] = up2
            if dut is not None:
                blk_meas.setdefault(dut, {})['%d|%s|%s' % (ct, ctitle, p['pin'])] = \
                    {'si': si, 'unit': it['baseUnit'], 'pass': ip, 'lo': lo2, 'up': up2}

    flush_block()
    # Sort 재계산 ((x,y) 등장순서)
    xyc = {}
    for rec in chip_records:
        if rec['x'] is not None and rec['y'] is not None:
            k = '%d,%d' % (rec['x'], rec['y']); xyc[k] = xyc.get(k, 0)+1; rec['sort'] = xyc[k]
        else: rec['sort'] = 1
    items = [imap[k] for k in iord if imap[k]['data']]
    return dict(hdr=hdr, items=items, duts=len(chip_records), chipRecords=chip_records)

def parse_data_line(line):
    tokens = line.split()
    if len(tokens) < 4: return None
    t0 = tokens[0]
    if len(t0) not in (5, 6) or not t0.isdigit(): return None    # 5/6자리 testid
    offset = 1; result = ''
    if tokens[1][:1].isalpha(): offset = 2; result = tokens[1]   # RESULT 마커
    if len(tokens) < offset+3: return None
    pin = ''
    if len(tokens) >= offset+5 and not tokens[offset+3].isdigit(): pin = tokens[offset+3]
    last = tokens[-1]
    cand = tokens[-2] if last[:1].isalpha() else last
    try: dut = int(cand)
    except ValueError: dut = None
    return dict(tid=int(t0), val=tokens[offset], up=tokens[offset+1], lo=tokens[offset+2],
                pin=pin, dut=dut, result=result)


def parse_file_records(log_path, cfg, *, allowed_tids=None, group_by_tid=False, on_progress=None):
    """Read UTF-8 DataLog records without rendering a histogram."""
    import os
    total = os.path.getsize(log_path) or 1
    replaced = 0
    def lines():
        # 청크(2MB) 단위로 읽어 '완성된 라인'만 한 번에 디코딩(라인당 디코딩 제거 → C 속도)
        # 진행률은 읽은 바이트/전체크기 (파일 기준이라 스트리밍서도 매끄러운 %). \n 경계로 잘라 멀티바이트 안전.
        nonlocal replaced
        read = 0; last = -1; tail = b''
        with open(log_path, 'rb') as f:
            while True:
                chunk = f.read(1 << 21)        # 2MB
                if not chunk:
                    break
                read += len(chunk)
                data = tail + chunk
                nl = data.rfind(b'\n')
                if nl < 0:
                    tail = data; continue
                tail = data[nl+1:]
                text = data[:nl].decode('utf-8', 'replace')
                replaced += text.count('\ufffd')
                for ln in text.split('\n'):
                    yield ln
                if on_progress:
                    pct = int(read * 100 / total)
                    if pct != last:
                        last = pct; on_progress(pct)
            if tail:
                text = tail.decode('utf-8', 'replace')
                replaced += text.count('\ufffd')
                yield text
        if on_progress: on_progress(100)
    parsed = parse_datalog(lines(), cfg, allowed_tids=allowed_tids, group_by_tid=group_by_tid)
    if replaced:
        parsed.setdefault("hdr", {})["decode_replaced"] = str(replaced)
    return parsed
