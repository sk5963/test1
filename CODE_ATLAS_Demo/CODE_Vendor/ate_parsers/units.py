"""Shared DataLog numeric tokens and engineering units (legacy-compatible)."""
import re

_PARSE_PREFIX = [('M',1e6),('K',1e3),('k',1e3),('',1),('m',1e-3),('u',1e-6),
                 ('n',1e-9),('p',1e-12),('f',1e-15),('a',1e-18)]
_DISP_PREFIX  = [('M',1e6),('K',1e3),('',1),('m',1e-3),('u',1e-6),('n',1e-9),('p',1e-12),('f',1e-15)]
_BASES = ['V','A','R','W','S','Hz']
UM = {}
UNIT_GROUPS = []
for _b in _BASES:
    for _p,_m in _PARSE_PREFIX: UM[_p+_b] = _m
    UNIT_GROUPS.append([_p+_b for _p,_ in _DISP_PREFIX])
UK = sorted(UM.keys(), key=lambda u:-len(u))   # 긴 단위 우선 매칭

def get_unit_group(u):
    for g in UNIT_GROUPS:
        if u in g: return g
    return None

_RE_VAL = re.compile(r'^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)([A-Za-z]+)?$')
_val_cache = {}    # 토큰→결과 메모(상한선 큰 단위 반복: up/lo/공통값 캐시 적중)
def parse_val(t):
    """'-106.0000mV' -> (SI_float, unit) | None.  정규식 1회 + 메모이제이션(고속)."""
    if t is None: return None
    c = _val_cache.get(t, 0)            # 0=미캐시 (None은 유효 결과라 센티넬로 0 사용)
    if c != 0: return c
    ts = t.strip()
    if ts == '' or ts.upper() == 'NONE':
        r = None
    else:
        m = _RE_VAL.match(ts)
        if not m:
            r = None
        else:
            num = float(m.group(1)); u = m.group(2) or ''
            r = (num*UM[u], u) if u in UM else (num, '')
    if len(_val_cache) < 200000: _val_cache[t] = r
    return r
