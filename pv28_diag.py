"""PV28-CW (Tuya co2bj / yrr3eiyiacm31ski) LAN 진단 도구.

SmartThings Edge 드라이버를 만들기 전에 이 기기가 로컬(LAN) 제어를 허용하는지,
어떤 프로토콜 버전을 쓰는지, 실제 DP 값이 어떻게 나오는지 확인한다.

    uv run pv28_diag.py ports                   # TCP 6668 열림 여부
    uv run pv28_diag.py probe                   # 키 없이 3.1/3.3 vs 3.4/3.5 판별
    uv run pv28_diag.py listen                  # UDP 브로드캐스트로 Device ID / 버전 확인
    uv run pv28_diag.py status --key <KEY>      # 버전 자동 감지 + DP 덤프 (기본 30초 x 10회)
    uv run pv28_diag.py multi --key <KEY>       # 동시 로컬 연결 허용 여부
    uv run pv28_diag.py write-test --key <KEY>  # DP 31(온도 단위) 쓰기 왕복 후 원래 값 복구
    uv run pv28_diag.py all [--key <KEY>]       # ports -> probe -> listen -> status -> multi

Device ID와 Local Key를 생략하면 `uv run python -m tinytuya wizard`가 만든 devices.json에서 찾는다.
결과는 diag-results/ 에 JSON으로 저장되며 Local Key는 기록하지 않는다.
"""
from __future__ import annotations

import argparse
import binascii
import datetime as dt
import json
import pathlib
import select
import socket
import struct
import subprocess
import sys
import time

import tinytuya
from tinytuya import scanner
from tinytuya.core.udp_helper import decrypt_udp

DEFAULT_IP = "192.168.0.7"
TCP_PORT = 6668
UDP_PORTS = (6666, 6667, 7000)
PRODUCT_ID = "yrr3eiyiacm31ski"
VERSIONS = (3.3, 3.4, 3.5, 3.1)
HERE = pathlib.Path(__file__).resolve().parent
RESULTS_DIR = HERE / "diag-results"

# DP 번호 -> (Tuya 코드, 설명, 표시 형식)
# 출처: make-all/tuya-local pv28-cw_airquality_monitor.yaml, HA fixture co2bj_yrr3eiyiacm31ski.json
DP_MAP = {
    "1": ("co2_state", "CO2 경보 상태", "raw"),
    "2": ("co2_value", "CO2", "ppm"),
    "5": ("alarm_volume", "경보 음량", "raw"),
    "6": ("alarm_ringtone", "경보음 종류", "raw"),
    "7": ("alarm_time", "경보 시간", "raw"),
    "13": ("alarm_switch", "경보 on/off", "raw"),
    "14": ("battery_state", "배터리 상태", "raw"),
    "15": ("battery_percentage", "배터리", "%"),
    "17": ("alarm_bright", "화면 밝기", "raw"),
    "18": ("temp_current", "온도", "deg"),
    "19": ("humidity_value", "습도", "%"),
    "20": ("pm25_value", "PM2.5", "ug/m3"),
    "21": ("voc_value", "TVOC", "milli"),
    "22": ("ch2o_value", "HCHO", "milli"),
    "26": ("maxco2_set", "CO2 경보 임계값", "ppm"),
    "31": ("temp_unit_convert", "온도 단위", "raw"),
    "101": ("pm10", "PM10", "ug/m3"),
    "102": ("pm25", "PM1.0 (코드명은 pm25)", "ug/m3"),
    "103": ("humidity_current", "습도 (중복)", "%"),
    "104": ("air_quality", "공기질 등급", "raw"),
    "105": ("pm25_set", "PM2.5 경보 임계값", "ug/m3"),
    "106": ("pm25_state", "PM2.5 경보 상태", "raw"),
    "107": ("check_time", "용도 미상 bool", "raw"),
    "108": ("screen_sleep", "화면 자동 꺼짐", "raw"),
    "109": ("screen_sleep_time", "화면 꺼짐 시간", "s"),
}
MEASUREMENT_DPS = ("2", "18", "19", "20", "21", "22", "101", "102")


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def fmt_dp(dp: str, value) -> str:
    code, label, kind = DP_MAP.get(dp, ("?", "목록에 없는 DP", "raw"))
    if kind == "milli" and isinstance(value, (int, float)):
        shown = f"{value}  (= {value / 1000:.3f} mg/m3 = {value} ug/m3)"
    elif kind != "raw":
        shown = f"{value} {kind}"
    else:
        shown = repr(value)
    return f"  DP {dp:>3}  {code:<20} {label:<22} {shown}"


def print_dps(dps: dict) -> None:
    for dp in sorted(dps, key=int):
        print(fmt_dp(dp, dps[dp]))


def has_dps(result) -> bool:
    return isinstance(result, dict) and isinstance(result.get("dps"), dict)


def describe_error(result) -> str:
    if result is None:
        return "응답 없음"
    if isinstance(result, dict) and "Err" in result:
        return f"{result.get('Err')} {result.get('Error')}"
    return repr(result)[:200]


class Report:
    def __init__(self, ip: str):
        self.data = {"started": now_iso(), "ip": ip, "tinytuya": tinytuya.__version__, "steps": {}}

    def add(self, step: str, result) -> None:
        self.data["steps"][step] = result

    def save(self) -> pathlib.Path:
        RESULTS_DIR.mkdir(exist_ok=True)
        path = RESULTS_DIR / f"diag-{dt.datetime.now():%Y%m%d-%H%M%S}.json"
        path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path


# ---------------------------------------------------------------- 1. ports

def ping(ip: str) -> bool:
    flag = ["-n", "1", "-w", "1000"] if sys.platform == "win32" else ["-c", "1", "-W", "1"]
    try:
        return subprocess.run(["ping", *flag, ip], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def check_port(ip: str, port: int, timeout: float = 3.0) -> dict:
    t0 = time.monotonic()
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            state = "open"
    except ConnectionRefusedError:
        state = "closed"
    except TimeoutError:
        state = "timeout"
    except OSError as e:
        state = f"error: {e}"
    return {"state": state, "ms": round((time.monotonic() - t0) * 1000)}


def cmd_ports(args, report: Report) -> dict:
    print(f"\n[1] {args.ip} 연결 확인")
    alive = ping(args.ip)
    print(f"  ping: {'응답' if alive else '응답 없음 (ICMP 차단일 수도 있음)'}")
    port = check_port(args.ip, TCP_PORT)
    print(f"  TCP {TCP_PORT}: {port['state']} ({port['ms']} ms)")
    if port["state"] == "open":
        print("  -> 로컬 TCP 포트가 열려 있습니다. 로컬 드라이버를 만들 수 있는 조건입니다.")
    elif port["state"] == "closed":
        print("  -> 기기는 응답하지만 6668이 닫혀 있습니다. Smart Life 앱을 완전히 종료(폰 Wi-Fi 끄기)한 뒤 다시 확인하세요.")
        print("     그래도 닫혀 있으면 이 개체는 로컬 제어를 막은 펌웨어일 수 있습니다 (tuya-local #2288 사례).")
    else:
        print("  -> 응답이 없습니다. IP가 맞는지, 기기가 켜져 있는지 확인하세요.")
    result = {"ping": alive, "tcp_6668": port}
    report.add("ports", result)
    return result


# ---------------------------------------------------------------- 1b. probe

def build_55aa(seqno: int, cmd: int, payload: bytes) -> bytes:
    header = struct.pack(">4I", 0x000055AA, seqno, cmd, len(payload) + 8)
    crc = binascii.crc32(header + payload) & 0xFFFFFFFF
    return header + payload + struct.pack(">2I", crc, 0x0000AA55)


def probe_once(ip: str, timeout: float = 5.0) -> dict:
    """암호화하지 않은 3.1식 DP_QUERY를 보내고 기기 반응을 본다 (tinytuya force-scan과 같은 원리).
    3.1/3.3 기기는 55AA 프레임으로 답하고, 3.4/3.5 기기는 세션 키 협상 없이 온 요청을 응답 없이 끊는다."""
    payload = json.dumps({"gwId": "", "devId": "", "uid": "", "t": str(int(time.time()))},
                         separators=(",", ":")).encode()
    t0 = time.monotonic()
    try:
        with socket.create_connection((ip, TCP_PORT), timeout=timeout) as s:
            s.sendall(build_55aa(1, 0x0A, payload))
            data = s.recv(1024)
    except TimeoutError:
        return {"result": "timeout"}
    except ConnectionResetError:
        return {"result": "reset", "ms": round((time.monotonic() - t0) * 1000)}
    except OSError as e:
        return {"result": f"error: {e}"}
    ms = round((time.monotonic() - t0) * 1000)
    if not data:
        return {"result": "closed", "ms": ms}
    info = {"result": "reply", "ms": ms, "prefix": data[:4].hex(), "len": len(data)}
    if data[:4] == b"\x00\x00\x55\xaa" and len(data) >= 20:
        _, seqno, cmd, length, retcode = struct.unpack(">5I", data[:20])
        info.update(cmd=cmd, length=length, retcode=retcode, body_head=data[20:40].hex())
    return info


def cmd_probe(args, report: Report) -> str:
    print("\n[1b] 키 없이 프로토콜 계열 판별 (3.1식 평문 DP_QUERY x3)")
    attempts = []
    for i in range(3):
        if i:
            time.sleep(1)
        r = probe_once(args.ip)
        attempts.append(r)
        print(f"  시도 {i + 1}: {r}")
    replies = [r for r in attempts if r["result"] == "reply"]
    if replies:
        body = bytes.fromhex(replies[0].get("body_head", ""))
        verdict = "3.3" if body.startswith(b"3.3") else "3.1/3.3"
        print(f"  -> 기기가 55AA 프레임으로 응답했습니다: v{verdict} 계열 (세션 키 협상 불필요)")
    elif all(r["result"] in ("closed", "reset") for r in attempts):
        verdict = "3.4/3.5"
        print("  -> 응답 없이 연결을 끊었습니다: v3.4 또는 v3.5 (세션 키 협상 + HMAC-SHA256 필요, 3.5면 AES-GCM)")
        print("     둘 중 어느 쪽인지는 Local Key를 얻은 뒤 status 단계의 자동 감지로 확정됩니다.")
    else:
        verdict = "unknown"
        print("  -> 판별 불가 (타임아웃/오류). 다른 로컬 클라이언트가 연결을 점유하고 있는지 확인하세요.")
    report.add("probe", {"attempts": attempts, "verdict": verdict})
    return verdict


# ---------------------------------------------------------------- 2. listen

def cmd_listen(args, report: Report) -> dict:
    print(f"\n[2] UDP {', '.join(map(str, UDP_PORTS))} 브로드캐스트 수신 ({args.seconds}초)")
    socks = []
    for port in UDP_PORTS:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("", port))
        except OSError as e:
            print(f"  UDP {port} bind 실패: {e}")
            s.close()
            continue
        socks.append(s)

    found: dict[str, dict] = {}
    deadline = time.monotonic() + args.seconds
    next_request = 0.0
    while socks and (remaining := deadline - time.monotonic()) > 0:
        if time.monotonic() >= next_request:
            # 3.5 신형 기기는 REQ_DEVINFO(0x25)를 UDP 7000으로 받아야 자기 정보를 보낸다
            try:
                scanner.send_discovery_request()
            except Exception as e:  # noqa: BLE001
                print(f"  discovery 요청 전송 실패: {e}")
            next_request = time.monotonic() + 5
        readable, _, _ = select.select(socks, [], [], min(remaining, 1.0))
        for s in readable:
            data, (src, _) = s.recvfrom(4096)
            port = s.getsockname()[1]
            if not args.all_hosts and src != args.ip:
                continue
            try:
                info = json.loads(decrypt_udp(data))
            except Exception as e:  # noqa: BLE001
                info = {"decode_error": str(e), "raw_len": len(data)}
            if info.get("from") == "app":  # 우리가 보낸 discovery 요청의 에코
                continue
            key = f"{src}:{port}"
            if key not in found:
                print(f"  {src} -> UDP {port}: gwId={info.get('gwId')} version={info.get('version')} "
                      f"productKey={info.get('productKey')} encrypt={info.get('encrypt')}")
            found[key] = info
    for s in socks:
        s.close()

    if not found:
        print("  수신된 브로드캐스트가 없습니다. Windows 방화벽이 python의 UDP 수신을 막았거나, 기기가 브로드캐스트를 하지 않는 경우입니다.")
        print("  (Edge 허브는 어차피 이 포트를 bind할 수 없으므로 드라이버에는 영향이 없습니다. Device ID는 wizard로 얻으면 됩니다.)")
    else:
        pk = {i.get("productKey") for i in found.values()} - {None}
        if pk and PRODUCT_ID not in pk:
            print(f"  ! productKey {pk} 가 PV28-CW({PRODUCT_ID})와 다릅니다. DP 표가 다를 수 있습니다.")
    report.add("listen", found)
    return found


# ---------------------------------------------------------------- credentials

def load_wizard_devices() -> list[dict]:
    for base in (pathlib.Path.cwd(), HERE):
        path = base / "devices.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                print(f"  devices.json 읽기 실패: {e}")
    return []


def resolve_creds(args, discovered_id: str | None = None) -> tuple[str | None, str | None, dict | None]:
    devices = load_wizard_devices()
    entry = None
    if devices:
        want_id = args.id or discovered_id
        if want_id:
            cands = [d for d in devices if d.get("id") == want_id]
        else:
            cands = [d for d in devices if d.get("ip") == args.ip] or \
                    [d for d in devices if d.get("product_id") == PRODUCT_ID]
        if len(cands) == 1:
            entry = cands[0]
        elif len(cands) > 1:
            print(f"  devices.json에 후보가 {len(cands)}개 있습니다. --id 로 지정하세요.")
    dev_id = args.id or (entry or {}).get("id") or discovered_id
    key = args.key or (entry or {}).get("key")
    return dev_id, key, entry


def compare_mapping(entry: dict | None) -> list[str]:
    """devices.json의 DP mapping(클라우드 기준)과 이 스크립트의 DP_MAP을 비교한다."""
    mapping = (entry or {}).get("mapping") or {}
    diffs = []
    for dp, spec in mapping.items():
        code = spec.get("code") if isinstance(spec, dict) else None
        expected = DP_MAP.get(str(dp), (None,))[0]
        if code != expected:
            diffs.append(f"DP {dp}: 클라우드={code} / 스크립트={expected}")
    return diffs


def print_key_help() -> None:
    print("  Local Key가 필요합니다. README의 'Local Key 확인'(tuyawizard)으로 만든 tuyadevices.json에서")
    print("  센서의 id와 local_key를 --id, --key로 넘기세요. tinytuya wizard가 만든 devices.json을 이 폴더에 둬도 됩니다.")


def make_device(dev_id: str, ip: str, key: str, ver: float, persist: bool = False) -> tinytuya.Device:
    return tinytuya.Device(dev_id, ip, key, version=ver, persist=persist,
                           connection_timeout=5, connection_retry_limit=1, connection_retry_delay=1)


# ---------------------------------------------------------------- 3. status

def detect_version(dev_id: str, ip: str, key: str, forced: float | None,
                   preferred: float | None = None) -> tuple[float | None, dict | None, list]:
    if forced:
        order = [forced]
    elif preferred in VERSIONS:
        order = [preferred, *(v for v in VERSIONS if v != preferred)]
    else:
        order = list(VERSIONS)
    attempts = []
    for ver in order:
        d = make_device(dev_id, ip, key, ver)
        try:
            r = d.status()
            dev_type = d.dev_type
        finally:
            d.close()
        ok = has_dps(r)
        attempts.append({"version": ver, "ok": ok, "dev_type": dev_type, "error": None if ok else describe_error(r)})
        print(f"  v{ver}: {'성공' if ok else '실패 - ' + describe_error(r)}" + (f" (dev_type={dev_type})" if ok else ""))
        if ok:
            return ver, r, attempts
        time.sleep(1)
    return None, None, attempts


def cmd_status(args, report: Report, dev_id: str, key: str, entry: dict | None,
               preferred: float | None = None) -> float | None:
    print(f"\n[3] 프로토콜 버전 감지 (Device ID {dev_id})")
    diffs = compare_mapping(entry)
    if entry and entry.get("mapping"):
        print("  devices.json DP mapping: " + ("스크립트 DP 표와 일치" if not diffs else "차이 있음"))
        for line in diffs:
            print(f"    {line}")

    ver, first, attempts = detect_version(dev_id, args.ip, key, args.ver, preferred)
    result = {"attempts": attempts, "version": ver, "mapping_diffs": diffs, "samples": []}
    report.add("status", result)
    if ver is None:
        print("  -> 모든 버전에서 실패했습니다. 914(key/version)면 Local Key를 다시 확인하세요(기기 재등록 시 바뀜).")
        print("     901/905면 다른 클라이언트(Smart Life 앱, HA 등)가 로컬 연결을 점유하고 있을 수 있습니다.")
        return None

    print(f"\n[4] DP 덤프: {args.count}회, {args.interval}초 간격 (v{ver}, 매번 연결 후 종료)")
    d = make_device(dev_id, args.ip, key, ver)
    history: dict[str, list] = {}
    prev: dict = {}
    for i in range(args.count):
        if i:
            time.sleep(args.interval)
        if args.updatedps:
            d.updatedps([int(x) for x in MEASUREMENT_DPS])
            time.sleep(1)
        r = first if i == 0 else d.status()
        d.close()
        stamp = now_iso()
        if not has_dps(r):
            print(f"  #{i + 1} {stamp} 실패: {describe_error(r)}")
            result["samples"].append({"t": stamp, "error": describe_error(r)})
            continue
        dps = {str(k): v for k, v in r["dps"].items()}
        result["samples"].append({"t": stamp, "dps": dps})
        for dp, v in dps.items():
            history.setdefault(dp, []).append(v)
        if i == 0:
            print(f"  #{i + 1} {stamp}")
            print_dps(dps)
        else:
            changed = {dp: v for dp, v in dps.items() if prev.get(dp) != v}
            print(f"  #{i + 1} {stamp} 변경 {len(changed)}개" + (":" if changed else ""))
            if changed:
                print_dps(changed)
        prev.update(dps)

    seen = set(history)
    unknown = sorted(seen - set(DP_MAP), key=int)
    missing = sorted(set(DP_MAP) - seen, key=int)
    frozen = [dp for dp in MEASUREMENT_DPS if dp in history and len(set(history[dp])) == 1]
    result["analysis"] = {"seen": sorted(seen, key=int), "unknown": unknown, "missing": missing, "unchanged_measurements": frozen}
    print("\n  요약")
    print(f"    받은 DP: {', '.join(sorted(seen, key=int))}")
    if unknown:
        print(f"    표에 없는 DP: {', '.join(unknown)}  -> 값과 의미를 확인해 DP 표에 추가")
    if missing:
        print(f"    표에는 있지만 안 온 DP: {', '.join(missing)}  (5/6/7/17/104는 원래 없을 수 있음)")
    if args.count > 1 and len(frozen) == len([dp for dp in MEASUREMENT_DPS if dp in history]):
        print("    ! 측정값이 한 번도 바뀌지 않았습니다. --updatedps 로 다시 시도하거나 간격을 늘려 보세요 (TuyaMCU 정지 이슈).")
    print("    확인할 것: DP 102 값이 앱의 PM1.0과 같은지, DP 21/22 원시값이 앱 수치 x1000인지")
    return ver


# ---------------------------------------------------------------- 5. multi

def socket_alive(sock) -> bool:
    if sock is None:
        return False
    try:
        readable, _, _ = select.select([sock], [], [], 0.2)
        if not readable:
            return True
        return len(sock.recv(4096, socket.MSG_PEEK)) > 0
    except OSError:
        return False


def cmd_multi(args, report: Report, dev_id: str, key: str, ver: float) -> dict:
    print(f"\n[5] 동시 연결 테스트 (v{ver})")
    a = make_device(dev_id, args.ip, key, ver, persist=True)
    ra = a.status()
    a_ok = has_dps(ra)
    print(f"  연결 A (유지): {'성공' if a_ok else '실패 - ' + describe_error(ra)}")
    if not a_ok:
        a.close()
        report.add("multi", {"a_ok": False})
        return {"a_ok": False}

    b = make_device(dev_id, args.ip, key, ver)
    rb = b.status()
    b.close()
    b_ok = has_dps(rb)
    print(f"  연결 B (A 유지 중): {'성공' if b_ok else '실패 - ' + describe_error(rb)}")
    a_alive = socket_alive(a.socket)
    print(f"  B 이후 A 소켓: {'살아 있음' if a_alive else '기기가 끊음'}")

    print(f"  A를 {args.hold}초 동안 아무것도 보내지 않고 유지...")
    time.sleep(args.hold)
    a_idle = socket_alive(a.socket)
    print(f"  유휴 {args.hold}초 후 A 소켓: {'살아 있음' if a_idle else '기기가 끊음'}")
    a.close()

    if b_ok and a_alive:
        print("  -> 로컬 연결을 2개 이상 받습니다. 허브 드라이버와 다른 로컬 클라이언트가 공존할 수 있습니다.")
    elif b_ok:
        print("  -> 새 연결이 들어오면 기존 연결을 끊습니다. 드라이버는 연결-조회-종료 방식이 안전합니다.")
    else:
        print("  -> 로컬 연결을 1개만 받습니다. 허브 드라이버를 쓰는 동안 다른 로컬 클라이언트는 쓰면 안 됩니다.")
    if not a_idle:
        print(f"  -> 유휴 {args.hold}초 안에 끊습니다. 지속 연결 모드에서는 그보다 짧은 하트비트가 필요합니다.")
    result = {"a_ok": a_ok, "b_ok": b_ok, "a_alive_after_b": a_alive, "a_alive_after_idle": a_idle, "hold": args.hold}
    report.add("multi", result)
    return result


# ---------------------------------------------------------------- 6. write-test

def cmd_write_test(args, report: Report, dev_id: str, key: str, ver: float) -> dict:
    print(f"\n[6] 쓰기 테스트: DP 31 온도 단위 (v{ver})")
    d = make_device(dev_id, args.ip, key, ver)
    r0 = d.status()
    if not has_dps(r0) or r0["dps"].get("31") not in ("c", "f"):
        print(f"  DP 31을 읽지 못해 건너뜁니다: {describe_error(r0) if not has_dps(r0) else r0['dps'].get('31')}")
        report.add("write_test", {"skipped": True})
        return {"skipped": True}
    orig, temp0 = r0["dps"]["31"], r0["dps"].get("18")
    target = "f" if orig == "c" else "c"
    d.set_value(31, target)
    time.sleep(3)
    r1 = d.status()
    d.set_value(31, orig)
    time.sleep(3)
    r2 = d.status()
    d.close()
    got = r1.get("dps", {}) if has_dps(r1) else {}
    back = r2.get("dps", {}).get("31") if has_dps(r2) else None
    ok = got.get("31") == target
    print(f"  {orig} -> {target}: {'반영됨' if ok else '반영 안 됨'} (온도 {temp0} -> {got.get('18')})")
    print(f"  원래 값 복구: {'완료' if back == orig else '확인 필요 (현재 ' + repr(back) + ')'}")
    result = {"orig": orig, "target": target, "applied": ok, "temp_before": temp0, "temp_after": got.get("18"), "restored": back == orig}
    report.add("write_test", result)
    return result


# ---------------------------------------------------------------- main

def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--ip", default=DEFAULT_IP, help=f"기기 IP (기본 {DEFAULT_IP})")
    common.add_argument("--id", help="Device ID (gwId). 생략하면 devices.json / UDP 브로드캐스트에서 찾음")
    common.add_argument("--key", help="16자 Local Key. 생략하면 devices.json에서 찾음")
    common.add_argument("--ver", type=float, choices=(3.1, 3.3, 3.4, 3.5), help="프로토콜 버전 고정 (기본: 자동 감지)")
    common.add_argument("--seconds", type=int, default=20, help="listen 시간 (초)")
    common.add_argument("--all-hosts", action="store_true", help="listen 시 다른 Tuya 기기도 표시")
    common.add_argument("--count", type=int, default=10, help="status 조회 횟수")
    common.add_argument("--interval", type=int, default=30, help="status 조회 간격 (초)")
    common.add_argument("--updatedps", action="store_true", help="조회 전에 UPDATEDPS(18)로 센서값 갱신 요청")
    common.add_argument("--hold", type=int, default=20, help="multi 테스트의 유휴 유지 시간 (초)")
    common.add_argument("--write-test", action="store_true", help="all 실행 시 쓰기 테스트도 포함")

    parser = argparse.ArgumentParser(description="PV28-CW Tuya LAN 진단")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("ports", "probe", "listen", "status", "multi", "write-test", "all"):
        sub.add_parser(name, parents=[common])
    args = parser.parse_args()

    report = Report(args.ip)
    report.data["command"] = args.cmd
    try:
        if args.cmd in ("ports", "all"):
            ports = cmd_ports(args, report)
            if args.cmd == "all" and ports["tcp_6668"]["state"] != "open":
                print("\n  6668이 열려 있지 않아 이후 단계는 건너뜁니다.")
                return 1
        if args.cmd in ("probe", "all"):
            cmd_probe(args, report)
        discovered_id = discovered_ver = None
        if args.cmd in ("listen", "all"):
            found = cmd_listen(args, report)
            mine = [i for k, i in found.items() if k.startswith(args.ip + ":")]
            ids = {i.get("gwId") for i in mine} - {None}
            vers = {i.get("version") for i in mine} - {None}
            discovered_id = ids.pop() if len(ids) == 1 else None
            discovered_ver = float(vers.pop()) if len(vers) == 1 else None
        if args.cmd in ("status", "multi", "write-test", "all"):
            dev_id, key, entry = resolve_creds(args, discovered_id)
            if not dev_id or not key:
                print(f"\n  Device ID: {dev_id or '없음'} / Local Key: {'있음' if key else '없음'}")
                print_key_help()
                return 1
            ver = args.ver
            if args.cmd in ("status", "all"):
                ver = cmd_status(args, report, dev_id, key, entry, discovered_ver)
            elif ver is None:
                ver, _, attempts = detect_version(dev_id, args.ip, key, None)
                report.add("version_detect", attempts)
            if ver is None:
                return 1
            if args.cmd in ("multi", "all"):
                cmd_multi(args, report, dev_id, key, ver)
            if args.cmd == "write-test" or (args.cmd == "all" and args.write_test):
                cmd_write_test(args, report, dev_id, key, ver)
        return 0
    except KeyboardInterrupt:
        print("\n  중단됨")
        return 130
    finally:
        print(f"\n결과 저장: {report.save().relative_to(HERE)}")


if __name__ == "__main__":
    sys.exit(main())
