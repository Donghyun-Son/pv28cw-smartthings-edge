"""driver/src/init.lua 를 SmartThings 라이브러리 모의 객체 위에서 Lua 5.3(lupa)으로 실행한다.

    uv run tests/test_driver.py           # DP 매핑·설정 쓰기·탐색·수명주기, 가짜 기기 상대 폴링 (기기 없이)
    uv run tests/test_driver.py --live    # + 실제 기기에서 init → 조회 → 이벤트 발행까지

허브의 cosock/st.* 대신 tests/test_lua.py의 소켓·JSON 대역과 가짜 Tuya 기기를 쓴다.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_lua as T  # noqa: E402

lua = T.lua
ROOT = T.ROOT

MOCKS = r"""
local captured = { logs = {}, created = {} }
local function logger(level) return function(msg) table.insert(captured.logs, level .. ": " .. tostring(msg)) end end
package.loaded["log"] = { info = logger("info"), warn = logger("warn"), debug = logger("debug"), error = logger("error") }
package.loaded["st.json"] = JSON
package.loaded["cosock"] = { socket = SOCKET }

-- capabilities[cap][attr](arg) -> { cap, attr, arg }
local caps = setmetatable({}, { __index = function(t, cap)
  local c = setmetatable({ ID = cap, commands = setmetatable({}, { __index = function(_, cmd) return { NAME = cmd } end }) },
    { __index = function(ct, attr)
        local f = setmetatable({}, { __call = function(_, arg) return { cap = cap, attr = attr, arg = arg } end })
        rawset(ct, attr, f)
        return f
      end })
  rawset(t, cap, c)
  return c
end })
package.loaded["st.capabilities"] = caps

package.loaded["st.driver"] = function(name, template)
  template.NAME = name
  template.devices = {}
  function template:run() end
  function template:get_devices() return self.devices end
  function template:try_create_device(info) table.insert(captured.created, info) end
  captured.driver = template
  return template
end

function captured.new_device(prefs)
  local d = { id = "dev-1", label = "PV28-CW test", preferences = prefs, fields = {}, persisted = {},
              events = {}, latest = {}, timers = {} }
  function d:emit_event(ev)
    table.insert(self.events, ev)
    self.latest[ev.cap .. "." .. ev.attr] = ev.arg.value
  end
  function d:get_latest_state(_, cap, attr) return self.latest[cap .. "." .. attr] end
  function d:online() self.state = "online" end
  function d:offline() self.state = "offline" end
  function d:get_field(k) return self.fields[k] end
  function d:set_field(k, v, opts)
    self.fields[k] = v
    if opts and opts.persist then self.persisted[k] = true end
  end
  d.thread = {
    call_on_schedule = function(_, interval, fn, name)
      local t = { interval = interval, fn = fn, name = name }
      table.insert(d.timers, t)
      return t
    end,
    call_with_delay = function(_, delay, fn, name)
      local t = { delay = delay, fn = fn, name = name }
      table.insert(d.timers, t)
      return t
    end,
    cancel_timer = function(_, t) t.cancelled = true end,
  }
  return d
end

function captured.run_timers(d)
  for _, t in ipairs(d.timers) do
    if not t.cancelled and not t.ran then t.ran = true; t.fn() end
  end
end

return captured
"""

# 2026-11-06 01:38 실기 값 (앱: PM2.5 7 / PM1.0 5 / PM10 8)
SAMPLE_DPS = {"1": "normal", "2": 803, "14": "normal", "15": 100, "18": 20, "19": 61, "20": 7, "21": 115,
              "22": 9, "101": 8, "102": 5, "106": "normal"}


def load_driver(factory=T.PySock):
    g = lua.globals()
    g.JSON = T.JSON_LIB
    g.SOCKET = T.socket_lib(factory)
    for mod in (b"init", b"dpmap", b"discovery"):
        lua.eval(f'function() package.loaded["{mod.decode()}"] = nil end')()
    cap = lua.execute(MOCKS)
    lua.eval('function() return require("init") end')()
    return cap


def prefs(**kw):
    base = {"ipAddress": "0.0.0.0", "localKey": "-", "pollInterval": 30, "temperatureCorrection": 0,
            "humidityCorrection": 0,
            "co2Alarm": "1500", "pm25Alarm": "75", "alarmSwitch": False, "screenSleep": True, "addDevice": False}
    base.update(kw)
    return T.to_lua(base)


def info_changed(drv, d, **changes):
    old = d.preferences
    d.preferences = prefs(**{**{k.decode(): (v.decode() if isinstance(v, bytes) else v) for k, v in old.items()},
                             **changes})
    args = lua.table_from({b"old_st_store": lua.table_from({b"preferences": old})})
    drv.lifecycle_handlers.infoChanged(drv, d, b"infoChanged", args)


def events_of(device) -> dict:
    out = {}
    for ev in device.events.values():
        arg = ev.arg
        out[f"{ev.cap.decode()}.{ev.attr.decode()}"] = (
            arg.value.decode() if isinstance(arg.value, bytes) else arg.value,
            arg.unit.decode() if arg.unit else None)
    return out


def logs(cap, level: str) -> list[str]:
    return [x.decode() for x in cap.logs.values() if x.startswith(level.encode() + b":")]


def test_dpmap() -> None:
    dpmap = lua.eval('require "dpmap"')
    evs = {f"{e.cap.decode()}.{e.attr.decode()}": (e.value.decode() if isinstance(e.value, bytes) else e.value,
                                                   e.unit.decode() if e.unit else None)
           for e in dpmap.events(T.to_lua(SAMPLE_DPS)).values()}
    T.check(evs["carbonDioxideMeasurement.carbonDioxide"] == (803, "ppm"), "co2")
    T.check(evs["fineDustSensor.fineDustLevel"] == (7, "μg/m^3"), "pm2.5")
    T.check(evs["dustSensor.fineDustLevel"] == (7, "μg/m^3"), "pm2.5 on dustSensor")
    T.check(evs["veryFineDustSensor.veryFineDustLevel"] == (5, "μg/m^3"), "pm1.0 from DP 102")
    T.check(evs["dustSensor.dustLevel"] == (8, "μg/m^3"), "pm10")
    T.check(evs["tvocMeasurement.tvocLevel"] == (115, "ug/m3"), "tvoc raw ug/m3")
    T.check(evs["formaldehydeMeasurement.formaldehydeLevel"] == (0.009, "mg/m^3"), "hcho /1000")
    T.check(evs["temperatureMeasurement.temperature"] == (20, "C"), "temp")
    T.check(evs["battery.battery"] == (100, None), "battery")
    T.check(evs["airQualityHealthConcern.airQualityHealthConcern"] == ("good", None), "overall good")
    T.check(len(evs) == 11, f"event count {len(evs)}")
    T.check(not any(k.endswith("HealthConcern") and not k.startswith("airQuality") for k in evs),
            "no per-pollutant health concern (aligned with Matter sensor)")
    # 등급 경계와 기기 경보 반영. 등급 값은 Matter 센서의 supportedAirQualityValues 안에서만
    supported = {v.decode() for v in dpmap.SUPPORTED_AIR_QUALITY.values()}
    lvl = lambda kind, v: dpmap.level(kind.encode(), v).decode()  # noqa: E731
    pm25 = [lvl("pm25", v) for v in (15, 16, 35, 36, 75, 76)]
    T.check(pm25 == ["good", "slightlyUnhealthy", "slightlyUnhealthy", "unhealthy", "unhealthy", "veryUnhealthy"],
            "pm25 levels")
    T.check([lvl("co2", v) for v in (1000, 1001, 2001)] == ["good", "slightlyUnhealthy", "unhealthy"], "co2 levels")
    T.check(set(pm25) <= supported and supported == {"unknown", "good", "slightlyUnhealthy", "unhealthy", "veryUnhealthy"},
            "levels within supported values")
    alarm = {e.attr.decode(): e.value.decode() for e in dpmap.events(T.to_lua({"2": 800, "1": "alarm"})).values()
             if isinstance(e.value, bytes)}
    T.check(alarm["airQualityHealthConcern"] == "unhealthy", "device co2 alarm raises overall concern")
    T.check(len(dpmap.events(T.to_lua({"1": "normal", "14": "normal"}))) == 0, "no events without measurement DPs")
    # 습도 보정: 습도에만 더하고 0~100으로 자름, 정수 유지. 보정 0이나 preference 없음은 원래 값
    def measured(dps, **kw):
        evs = dpmap.events(T.to_lua(dps), prefs(**kw))
        return {e.attr.decode(): e.value for e in evs.values()}
    corrected = measured(SAMPLE_DPS, humidityCorrection=-11)
    T.check(corrected["humidity"] == 50 and isinstance(corrected["humidity"], int), "humidity correction")
    T.check(corrected["temperature"] == 20 and corrected["carbonDioxide"] == 803, "correction only touches humidity")
    T.check(measured({"19": 95}, humidityCorrection=10)["humidity"] == 100, "corrected humidity clamped to 100")
    T.check(measured({"19": 3}, humidityCorrection=-5)["humidity"] == 0, "corrected humidity clamped to 0")
    T.check(measured({"19": 61}, humidityCorrection="-3")["humidity"] == 58, "string preference value")
    T.check(measured({"19": 61})["humidity"] == 61, "no correction by default")
    # 온도 보정: 소수 가능(소수 첫째 자리로 반올림), 자르지 않음, 습도와 따로
    corrected = measured(SAMPLE_DPS, temperatureCorrection=-1.5)
    T.check(corrected["temperature"] == 18.5 and corrected["humidity"] == 61, "temperature correction")
    T.check(measured({"18": 20}, temperatureCorrection=-0.3)["temperature"] == 19.7, "no float noise (19.7)")
    T.check(measured({"18": 20}, temperatureCorrection=0.05)["temperature"] == 20.1, "rounded to 0.1")
    t = measured({"18": 20}, temperatureCorrection=2.0)["temperature"]
    T.check(t == 22 and isinstance(t, int), "whole-degree correction stays integer")
    T.check(measured({"18": 3}, temperatureCorrection=-10)["temperature"] == -7, "temperature below zero not clamped")
    both = measured(SAMPLE_DPS, temperatureCorrection=1, humidityCorrection=-1)
    T.check((both["temperature"], both["humidity"]) == (21, 60), "temperature and humidity corrected together")
    T.check(dpmap.corrections_changed(prefs(), prefs(humidityCorrection=-5)), "correction change detected")
    T.check(dpmap.corrections_changed(prefs(), prefs(temperatureCorrection=-0.5)), "temperature correction change")
    T.check(not dpmap.corrections_changed(prefs(), prefs(co2Alarm="900")), "other settings are not corrections")
    T.check(not dpmap.corrections_changed(lua.table_from({}), prefs()), "missing old correction equals 0")
    # 설정 쓰기: 바뀐 것만, 목록 문자열과 예전 정수 값 모두 범위·단위 맞춤, 최초 생성(old 없음)은 무시
    w = dpmap.setting_writes(prefs(), prefs(co2Alarm="900", screenSleep=False))
    T.check(dict(w.items()) == {b"26": 900, b"108": False}, f"setting writes {dict(w.items())}")
    T.check(dict(dpmap.setting_writes(prefs(), prefs(co2Alarm=1234)).items()) == {b"26": 1200}, "legacy int rounded")
    T.check(dpmap.setting_writes(prefs(), prefs()) is None, "no writes when unchanged")
    T.check(dpmap.setting_writes(prefs(), prefs(co2Alarm=1500)) is None, "legacy int equal to option is unchanged")
    T.check(dpmap.setting_writes(lua.table_from({}), prefs(co2Alarm="900")) is None, "no writes on first prefs")
    T.check(dict(dpmap.setting_writes(prefs(pm25Alarm="50"), prefs(pm25Alarm=99)).items()) == {b"105": 75}, "pm25 clamp")
    T.check(dpmap.setting_writes(prefs(), prefs(pm25Alarm=99)) is None, "clamped value equal to current is unchanged")


def test_lifecycle_unconfigured() -> None:
    cap = load_driver()
    drv = cap.driver
    T.check(drv.NAME == b"pv28cw-tuya-lan", "driver name")
    # 탐색: 기기가 없으면 자리표시자 생성, 설정 전 기기가 있으면 생성 안 함
    drv.discovery(drv, None, lambda: True)
    T.check(len(cap.created) == 1 and cap.created[1].type == b"LAN" and cap.created[1].profile == b"pv28cw-air-monitor"
            and cap.created[1].label.decode() == "공기질 센서", "discovery creates placeholder")
    d = cap.new_device(prefs())
    drv.devices[1] = d
    drv.discovery(drv, None, lambda: True)
    T.check(len(cap.created) == 1, "discovery skips while placeholder unconfigured")
    # 설정을 마친 기기만 있어도 주변 기기 검색으로는 더 만들지 않음 (다른 기기를 찾을 때도 불리므로)
    configured = cap.new_device(prefs(ipAddress="192.168.0.50", localKey=T.LOCAL_KEY.decode()))
    drv.devices[1] = configured
    drv.discovery(drv, None, lambda: True)
    T.check(len(cap.created) == 1, "discovery does not add a device when one already exists")
    drv.devices[1] = d
    # 설정 전 기기: init은 supported values만 보내고 조회 타이머를 걸지 않음
    drv.lifecycle_handlers.init(drv, d)
    drv.lifecycle_handlers.added(drv, d)
    T.check(len(d.events) == 1 and d.events[1].attr == b"supportedAirQualityValues", "init emits supported values once")
    T.check(list(d.events[1].arg.values()) == [b"unknown", b"good", b"slightlyUnhealthy", b"unhealthy", b"veryUnhealthy"],
            "supported values match Matter sensor")
    T.check(len(d.timers) == 0 and d.state == b"offline", "unconfigured device is not polled")
    T.check(any("IP 주소" in x for x in logs(cap, "info")), "log names the missing setting")
    # 설정 전에 바꾼 센서 설정은 대기열(영구)에 남는다
    info_changed(drv, d, co2Alarm="1200")
    T.check(dict(d.fields[b"pending_writes"].items()) == {b"26": 1200} and d.persisted[b"pending_writes"],
            "setting change kept as persistent pending write")
    # 공백이 붙은 IP는 받고, 잘못된 IP/키는 어느 항목인지 알려 준다
    discovery = lua.eval('require "discovery"')
    conn = discovery.connection(cap.new_device(prefs(ipAddress=" 192.168.0.50 ", localKey=" 0123456789abcdef\n")))
    T.check(conn.ip == b"192.168.0.50" and conn.local_key == b"0123456789abcdef", "connection trims whitespace")
    for ip, key, problem in (("192.168.0.256", "0123456789abcdef", "IP"), ("192.168.0.50", "short", "Local Key")):
        res = discovery.connection(cap.new_device(prefs(ipAddress=ip, localKey=key)))
        T.check(res[0] is None and problem in res[1].decode(), f"invalid {problem}")


def test_add_device() -> None:
    cap = load_driver()
    drv = cap.driver
    d1 = cap.new_device(prefs(ipAddress="192.168.0.50", localKey=T.LOCAL_KEY.decode()))
    d1.label = "공기질 센서".encode()
    drv.devices[1] = d1
    # "새 기기 추가" 스위치를 바꾸면 설정 전 기기를 하나 만들고, 이름이 겹치지 않게 번호를 붙임
    info_changed(drv, d1, addDevice=True)
    T.check(len(cap.created) == 1 and cap.created[1].label.decode() == "공기질 센서 2"
            and cap.created[1].profile == b"pv28cw-air-monitor", "add device switch creates numbered placeholder")
    T.check(len(d1.timers) == 0, "add device switch does not restart polling")
    # 바로 다시 꺼도(만든 기기가 아직 목록에 없음) 하나만 만듦
    info_changed(drv, d1, addDevice=False)
    T.check(len(cap.created) == 1, "no duplicate while creation is pending")
    # 만든 기기가 목록에 나온 뒤에도 설정하기 전까지는 더 만들지 않음
    d2 = cap.new_device(prefs())
    d2.label = cap.created[1].label
    d2.device_network_id = cap.created[1].device_network_id
    drv.devices[2] = d2
    info_changed(drv, d1, addDevice=True)
    T.check(len(cap.created) == 1, "no new device while one is unconfigured")
    # 새 기기를 설정하면 어느 기기의 스위치로든 하나 더 만들 수 있음
    d2.preferences = prefs(ipAddress="192.168.0.51", localKey=T.LOCAL_KEY.decode())
    info_changed(drv, d2, addDevice=True)
    T.check(len(cap.created) == 2 and cap.created[2].label.decode() == "공기질 센서 3", "next placeholder after configuring")
    T.check(cap.created[1].device_network_id != cap.created[2].device_network_id, "unique network ids")
    # 만든 기기가 끝내 나오지 않으면(생성 실패) 60초 뒤에는 다시 만들 수 있음
    info_changed(drv, d2, addDevice=False)
    T.check(len(cap.created) == 2, "still pending")
    lua.execute("_REAL_TIME = os.time; os.time = function() return _REAL_TIME() + 61 end")
    try:
        info_changed(drv, d2, addDevice=True)
    finally:
        lua.execute("os.time = _REAL_TIME")
    T.check(len(cap.created) == 3, "retry allowed after pending timeout")
    # 기기를 처음 만들거나 드라이버 업데이트로 설정이 새로 생길 때(이전 값 없음)는 만들지 않음
    cap = load_driver()
    drv = cap.driver
    d = cap.new_device(prefs(ipAddress="192.168.0.50", localKey=T.LOCAL_KEY.decode()))
    drv.devices[1] = d
    for value in (False, True):
        d.preferences = prefs(ipAddress="192.168.0.50", localKey=T.LOCAL_KEY.decode(), addDevice=value)
        old = lua.table_from({k: v for k, v in d.preferences.items() if k != b"addDevice"})
        args = lua.table_from({b"old_st_store": lua.table_from({b"preferences": old})})
        drv.lifecycle_handlers.infoChanged(drv, d, b"infoChanged", args)
    T.check(len(cap.created) == 0, "new preference appearing does not create a device")


def test_polling_fake_device() -> None:
    dev = T.FakeTuya(SAMPLE_DPS)
    cap = load_driver(dev.factory)
    drv = cap.driver
    d = cap.new_device(prefs())
    drv.devices[1] = d
    drv.lifecycle_handlers.init(drv, d)
    # 설정 전에 바꾼 센서 설정 → 연결 설정 입력 → 첫 조회에서 쓰고 대기열을 비움
    info_changed(drv, d, co2Alarm="1200")
    T.check(not dev.sockets, "no connection while unconfigured")
    info_changed(drv, d, ipAddress="192.168.0.50", localKey=T.LOCAL_KEY.decode())
    T.check(len(d.timers) == 2 and d.timers[1].interval == 30, "connection settings start polling")
    cap.run_timers(d)  # 주기 타이머 + 첫 조회 = 조회 2번
    T.check(dev.writes == [{"26": 1200}] and d.fields[b"pending_writes"] is None, "pending write sent on first poll")
    T.check(d.state == b"online" and len(d.events) == 12, f"11 events + supported values, got {len(d.events)}")
    # 같은 값이면 보내지 않고, 바뀐 값만 보냄
    refresh = drv.capability_handlers[b"refresh"][b"refresh"]
    refresh(drv, d)
    T.check(len(d.events) == 12, "unchanged values are not re-emitted")
    dev.dps["2"] = 1500
    refresh(drv, d)
    T.check({e.attr for e in list(d.events.values())[12:]} == {b"carbonDioxide", b"airQualityHealthConcern"},
            "only changed values emitted")
    # 습도 보정을 바꾸면 다음 주기를 기다리지 않고 다시 조회해 보정한 습도만 보냄
    n = len(d.events)
    info_changed(drv, d, humidityCorrection=-11)
    T.check([(e.attr, e.arg.value) for e in list(d.events.values())[n:]] == [(b"humidity", 50)],
            "humidity correction applied right away")
    n = len(d.events)
    info_changed(drv, d, temperatureCorrection=-1.5)
    T.check([(e.attr, e.arg.value) for e in list(d.events.values())[n:]] == [(b"temperature", 18.5)],
            "temperature correction applied right away")
    # 응답에 측정값이 없으면 실패로 세고, 3번째에 offline, 4번째부터 debug 로그
    dev.query_payload = b"device busy"
    for _ in range(4):
        refresh(drv, d)
    fails = [x for x in cap.logs.values() if "조회 실패".encode() in x]
    T.check(d.state == b"offline" and d.fields[b"poll_failures"] == 4, "empty replies count as failures")
    T.check([x.split(b":")[0] for x in fails] == [b"warn", b"warn", b"warn", b"debug"], "quiet after offline")
    dev.query_payload = None
    refresh(drv, d)
    T.check(d.state == b"online" and any("다시 연결됨" in x for x in logs(cap, "info")), "recovers")
    # 연결이 안 되면 대기열을 남겨 두고 다음 조회 때 씀
    dev.reachable = False
    info_changed(drv, d, pm25Alarm="50")
    T.check(dict(d.fields[b"pending_writes"].items()) == {b"105": 50}, "pending kept while unreachable")
    dev.reachable = True
    refresh(drv, d)
    T.check(dev.writes[-1] == {"105": 50} and d.fields[b"pending_writes"] is None, "pending retried")
    # 기기가 쓰기에 답하지 않아도 조회가 되면 대기열을 비우고 경고 (매번 실패하지 않게)
    dev.control_reply = False
    info_changed(drv, d, alarmSwitch=True)
    T.check(d.fields[b"pending_writes"] is None and d.state == b"online", "ignored write dropped, poll succeeds")
    T.check(any("설정 쓰기 실패" in x for x in logs(cap, "warn")), "ignored write is logged")
    T.check(all(s.closed for s in dev.sockets), "every poll closes its socket")


def test_lifecycle_live(ip: str) -> None:
    devices = json.loads((ROOT / "devices.json").read_text(encoding="utf-8"))
    dev = next(x for x in devices if x.get("product_id") == "yrr3eiyiacm31ski")
    cap = load_driver()
    drv = cap.driver
    d = cap.new_device(prefs())
    drv.devices[1] = d
    drv.lifecycle_handlers.init(drv, d)
    # 사용자가 설정에 IP/Key 입력 → infoChanged → 폴링 시작
    info_changed(drv, d, ipAddress=ip, localKey=dev["key"])
    T.check(len(d.timers) == 2, "infoChanged starts polling")
    cap.run_timers(d)
    evs = {k: v for k, v in events_of(d).items() if not k.endswith("supportedAirQualityValues")}
    for k, v in sorted(evs.items()):
        print(f"    {k} = {v[0]!r}" + (f" {v[1]}" if v[1] else ""))
    T.check(d.state == b"online", "live device online")
    T.check(len(evs) == 11, f"live event count {len(evs)}")
    # refresh 명령: 바뀐 값만 다시 보냄
    n = len(d.events)
    drv.capability_handlers[b"refresh"][b"refresh"](drv, d)
    T.check(d.state == b"online" and len(d.events) - n <= 11, "refresh")
    warns = logs(cap, "warn")
    T.check(not warns, f"no warnings: {warns}")


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--ip", default="192.168.0.7")
    args = ap.parse_args()
    for t in (test_dpmap, test_lifecycle_unconfigured, test_add_device, test_polling_fake_device):
        t()
        print(f"{t.__name__}: ok")
    if args.live:
        test_lifecycle_live(args.ip)
        print("test_lifecycle_live: ok")
    print(f"{T.passed} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
