"""driver/src/tuya Lua 모듈을 Lua 5.3(lupa)에서 실행해 Python 기준 구현과 비교한다.

    uv run tests/test_lua.py               # 암호·프레임 벡터, 가짜 기기 상대 세션 테스트
    uv run tests/test_lua.py --live        # + 실제 기기에서 Lua 클라이언트로 조회 (devices.json 필요)
    uv run tests/test_lua.py --live-write  # + DP 31을 현재 값 그대로 다시 써서 CONTROL_NEW 경로 확인
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import pathlib
import socket
import struct
import sys
import time

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from lupa import lua53
from tinytuya.core.message_helper import TuyaMessage, pack_message

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "driver" / "src").as_posix()

lua = lua53.LuaRuntime(encoding=None, unpack_returned_tuples=True)
lua.execute(f'package.path = "{SRC}/?.lua;" .. package.path')
aes = lua.eval('require "tuya.aes"')
gcm = lua.eval('require "tuya.gcm"')
sha = lua.eval('require "tuya.sha256"')
proto = lua.eval('require "tuya.protocol"')
Client = lua.eval('require "tuya.client"')

# 드라이버가 session 안에서 하는 일과 같은 조합
FETCH = lua.eval("function(c) return c:session(function() return c:query() end) end")
APPLY = lua.eval("""function(c, dps) return c:session(function()
  local ok, err = c:control(dps)
  if not ok then return nil, err end
  return c:query()
end) end""")

passed = 0


def check(cond: bool, what: str) -> None:
    global passed
    if not cond:
        raise AssertionError(what)
    passed += 1


def test_aes() -> None:
    for n in range(40):
        key, block = os.urandom(16), os.urandom(16)
        enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        check(aes.encrypt_block(aes.expand_key(key), block) == enc.update(block) + enc.finalize(), f"AES block #{n}")


def test_gcm() -> None:
    for n in range(60):
        key, iv = os.urandom(16), os.urandom(12)
        pt, aad = os.urandom(n * 3 % 101), os.urandom(n % 31)
        ref = AESGCM(key).encrypt(iv, pt, aad)
        ct, tag = gcm.encrypt(key, iv, pt, aad)
        check(ct + tag == ref, f"GCM encrypt len={len(pt)} aad={len(aad)}")
        check(gcm.decrypt(key, iv, ct, aad, tag) == pt, "GCM decrypt")
        bad = bytes([tag[0] ^ 1]) + tag[1:]
        check(gcm.decrypt(key, iv, ct, aad, bad) == (None, b"auth"), "GCM tamper detection")


def test_sha256() -> None:
    for n in [0, 1, 55, 56, 63, 64, 65, 119, 120, 200, 1000]:
        msg = os.urandom(n)
        check(sha.digest(msg) == hashlib.sha256(msg).digest(), f"SHA-256 len={n}")
    for klen in (16, 64, 100):
        key, msg = os.urandom(klen), os.urandom(77)
        check(sha.hmac(key, msg) == hmac.new(key, msg, hashlib.sha256).digest(), f"HMAC key={klen}")


def test_frames() -> None:
    key, iv = os.urandom(16), os.urandom(12)
    # 클라이언트 프레임: 버전 헤더 없는 명령(16)과 있는 명령(13)
    for cmd, payload, header in ((16, b"{}", b""), (13, b'{"protocol":5,"t":1,"data":{"dps":{"31":"c"}}}', b"3.5" + b"\0" * 12)):
        ref = pack_message(TuyaMessage(7, cmd, None, header + payload, 0, True, 0x6699, iv), hmac_key=key)
        check(proto.pack(7, cmd, payload, key, iv) == ref, f"pack cmd {cmd}")
    # 기기 프레임: retcode + 버전 헤더 + JSON
    body = b"3.5" + b"\0" * 12 + b'{"dps":{"2":788,"31":"c"}}'
    dev = pack_message(TuyaMessage(42, 16, 0, body, 0, True, 0x6699, iv), hmac_key=key)
    msg = proto.unpack(dev, key)
    check(msg is not None and msg[b"cmd"] == 16 and msg[b"seqno"] == 42 and msg[b"retcode"] == 0, "unpack header")
    check(msg[b"payload"] == b'{"dps":{"2":788,"31":"c"}}', "unpack payload")
    check(proto.unpack(dev, os.urandom(16)) == (None, b"auth"), "unpack wrong key")
    # 세션 키 협상: tinytuya _negotiate_session_key_generate_* 와 같은 계산
    local_key, ln, rn = os.urandom(16), os.urandom(16), os.urandom(16)
    resp = rn + hmac.new(local_key, ln, hashlib.sha256).digest()
    finish, session = proto.finish_negotiation(local_key, ln, resp)
    xored = bytes(a ^ b for a, b in zip(ln, rn))
    check(finish == hmac.new(local_key, rn, hashlib.sha256).digest(), "negotiation finish HMAC")
    check(session == AESGCM(local_key).encrypt(ln[:12], xored, None)[:16], "3.5 session key")
    check(proto.finish_negotiation(os.urandom(16), ln, resp)[0] is None, "negotiation rejects wrong key")
    # CONTROL_NEW 페이로드 (공백 없음, DP 정렬)
    dps = lua.table_from({b"31": b"c", b"13": False, b"26": 1500})
    check(proto.control_payload(dps, 1700000000) ==
          b'{"protocol":5,"t":1700000000,"data":{"dps":{"13":false,"26":1500,"31":"c"}}}', "control payload")


# ---------------------------------------------------------------- 소켓·JSON 대역

class PySock:
    """cosock.socket처럼 동작하는 최소 소켓 (receive(n)은 정확히 n바이트)."""

    def __init__(self):
        self.s, self.timeout = None, 5

    def settimeout(self, t):
        self.timeout = t

    def connect(self, ip, port):
        try:
            self.s = socket.create_connection((ip.decode(), port), timeout=self.timeout)
            return 1
        except OSError as e:
            return None, str(e).encode()

    def send(self, data):
        self.s.sendall(data)
        return len(data)

    def receive(self, n):
        buf = b""
        try:
            while len(buf) < n:
                chunk = self.s.recv(n - len(buf))
                if not chunk:
                    return None, b"closed", buf
                buf += chunk
        except TimeoutError:
            return None, b"timeout", buf
        return buf

    def close(self):
        if self.s:
            self.s.close()


LOCAL_KEY = b"0123456789abcdef"


def _device_frame(key: bytes, seqno: int, cmd: int, payload: bytes, retcode: int = 0) -> bytes:
    body = struct.pack(">I", retcode) + payload
    iv = os.urandom(12)
    header = struct.pack(">IHIII", 0x6699, 0, seqno, cmd, len(body) + 12 + 16)
    return header + iv + AESGCM(key).encrypt(iv, body, header[4:]) + b"\0\0\x99\x66"


class FakeTuya:
    """세션 키 협상, DP_QUERY_NEW, CONTROL_NEW에 답하는 Tuya 3.5 기기 대역 (cryptography로 직접 구현)."""

    def __init__(self, dps: dict, key: bytes = LOCAL_KEY):
        self.dps, self.key = dict(dps), key
        self.reachable = True
        self.control_reply = True       # False면 CONTROL_NEW에 답하지 않는다
        self.query_payload = None       # bytes면 DP_QUERY_NEW 응답 내용을 이것으로 바꾼다
        self.writes: list[dict] = []
        self.sockets: list[FakeSocket] = []

    def factory(self):
        sock = FakeSocket(self)
        self.sockets.append(sock)
        return sock


class FakeSocket:
    def __init__(self, dev: FakeTuya):
        self.dev, self.key, self.inbox, self.seqno = dev, dev.key, b"", 100
        self.closed = self.dropped = False

    def settimeout(self, t):
        pass

    def connect(self, ip, port):
        return 1 if self.dev.reachable else (None, b"timeout")

    def _reply(self, cmd: int, payload: bytes, retcode: int = 0) -> None:
        self.inbox += _device_frame(self.key, self.seqno, cmd, payload, retcode)
        self.seqno += 1

    def send(self, data):
        _, _, _, cmd, length = struct.unpack(">IHIII", data[:18])
        try:
            plain = AESGCM(self.key).decrypt(data[18:30], data[30:18 + length], data[4:18])
        except InvalidTag:  # 키가 틀리면 실제 기기처럼 연결을 끊는다
            self.dropped = True
            return len(data)
        if plain.startswith(b"3.5"):
            plain = plain[15:]
        if cmd == 0x03:
            self.local_nonce, self.remote_nonce = plain, os.urandom(16)
            self._reply(0x04, self.remote_nonce + hmac.new(self.dev.key, plain, hashlib.sha256).digest())
        elif cmd == 0x05:
            xored = bytes(a ^ b for a, b in zip(self.local_nonce, self.remote_nonce))
            self.key = AESGCM(self.dev.key).encrypt(self.local_nonce[:12], xored, None)[:16]
        elif cmd == 0x10:
            self._reply(0x10, self.dev.query_payload or json.dumps({"dps": self.dev.dps}).encode())
        elif cmd == 0x0D and self.dev.control_reply:
            written = json.loads(plain)["data"]["dps"]
            self.dev.writes.append(written)
            self.dev.dps.update(written)
            self._reply(0x0D, b"")
            self._reply(0x08, b"3.5" + b"\0" * 12 + json.dumps({"dps": written}).encode())
        return len(data)

    def receive(self, n):
        if self.dropped:
            return None, b"closed"
        if len(self.inbox) < n:
            return None, b"timeout"
        chunk, self.inbox = self.inbox[:n], self.inbox[n:]
        return chunk

    def close(self):
        self.closed = True


def to_lua(obj):
    if isinstance(obj, dict):
        return lua.table_from({k.encode(): to_lua(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return lua.table_from([to_lua(v) for v in obj])
    if isinstance(obj, str):
        return obj.encode()
    return obj


JSON_LIB = lua.table_from({b"decode": lambda s: to_lua(json.loads(s))})

socket_lib = lua.eval("""function(factory)
  return { tcp = function()
    local py = factory()
    return {
      settimeout = function(_, t) py.settimeout(t) end,
      connect = function(_, ip, port) return py.connect(ip, port) end,
      send = function(_, d) return py.send(d) end,
      receive = function(_, n) return py.receive(n) end,
      close = function(_) py.close() end,
    }
  end }
end""")


def lua_table_to_dict(t) -> dict:
    return {k.decode(): (v.decode() if isinstance(v, bytes) else v) for k, v in t.items()}


def make_client(ip: str, key: str, factory=PySock, debug=lambda m: None):
    opts = lua.table_from({b"ip": ip.encode(), b"local_key": key.encode(), b"socket": socket_lib(factory),
                           b"json": JSON_LIB, b"log": lua.table_from({b"debug": debug})})
    return Client.new(opts)


def test_session() -> None:
    dev = FakeTuya({"2": 788, "31": "c"})
    client = make_client("192.168.0.50", LOCAL_KEY.decode(), dev.factory)
    dps, err = FETCH(client)
    check(err is None and lua_table_to_dict(dps) == {"2": 788, "31": "c"}, f"fake fetch: {err}")
    dps, err = APPLY(client, lua.table_from({b"31": b"f"}))
    check(err is None and dev.writes == [{"31": "f"}] and lua_table_to_dict(dps)["31"] == "f", "fake control + query")
    dps, err = client.session(client, lua.eval('function() error("boom") end'))
    check(dps is None and b"lua error" in err and b"boom" in err, f"lua error becomes nil, err: {err}")
    check(all(s.closed for s in dev.sockets), "every session closes its socket")
    dev.reachable = False
    dps, err = FETCH(client)
    check(dps is None and err.startswith(b"connect:"), f"unreachable: {err}")
    wrong = make_client("192.168.0.50", "fedcba9876543210", FakeTuya({}).factory)
    dps, err = FETCH(wrong)
    check(dps is None and err.startswith(b"negotiate:"), f"wrong key: {err}")


# ---------------------------------------------------------------- live

def test_live(ip: str, write: bool) -> None:
    devices = json.loads((ROOT / "devices.json").read_text(encoding="utf-8"))
    dev = next(d for d in devices if d.get("product_id") == "yrr3eiyiacm31ski")
    client = make_client(ip, dev["key"], debug=lambda m: print("    lua:", m.decode()))
    t0 = time.monotonic()
    dps, err = FETCH(client)
    ms = round((time.monotonic() - t0) * 1000)
    check(dps is not None, f"live fetch failed: {err}")
    got = lua_table_to_dict(dps)
    print(f"  live fetch ({ms} ms): {got}")
    check(all(k in got for k in ("2", "18", "19", "20", "21", "22", "101", "102")), "live: measurement DPs present")
    if write:
        # 현재 값을 그대로 다시 써서 CONTROL_NEW 응답(retcode 0)까지만 확인한다.
        # 값 반영 여부는 기기 상태에 따라 다르다 (DP 31은 tinytuya로 써도 반영되지 않는 때가 있었음).
        current = got["31"]
        dps, err = APPLY(client, lua.table_from({b"31": current.encode()}))
        check(dps is not None, f"live apply failed: {err}")
        print(f"  live apply 31={current!r}: ack ok, DP 31 now {lua_table_to_dict(dps).get('31')!r}")


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--live-write", action="store_true")
    ap.add_argument("--ip", default="192.168.0.7")
    args = ap.parse_args()
    tests = [test_aes, test_gcm, test_sha256, test_frames, test_session]
    for t in tests:
        t0 = time.monotonic()
        t()
        print(f"{t.__name__}: ok ({round((time.monotonic() - t0) * 1000)} ms)")
    if args.live or args.live_write:
        test_live(args.ip, args.live_write)
        print("test_live: ok")
    print(f"{passed} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
