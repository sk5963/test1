"""DDI 칩 출력단 VOH/VOL 전압 레벨 테스트 샘플 (데모/탐지 대상용).

의도적으로 흔한 ATE 스크립트 문제 패턴을 포함한다:
- 하드코딩 스펙 리밋, 계측기 호출에 예외처리 없음, timeout 미지정,
  부동소수점 '==' 판정, 리소스 close 누락, bin 기록 누락, 과도하게 긴 함수.
"""

import pyvisa


def test_voh_vol(site_num):
    rm = pyvisa.ResourceManager()
    dmm = rm.open_resource(f"GPIB0::{site_num}::INSTR")

    dmm.write("CONF:VOLT:DC")
    voh = float(dmm.query("READ?"))

    dmm.write("OUTP:STATE OFF")
    vol = float(dmm.query("READ?"))

    if voh > 2.4:
        voh_pass = True
    else:
        voh_pass = False

    if vol == 0.0:
        vol_pass = True
    else:
        vol_pass = False

    result = voh_pass and vol_pass
    return result
