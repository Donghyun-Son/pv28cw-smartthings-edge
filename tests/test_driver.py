"""driver/src/init.lua 를 SmartThings 라이브러리 모의 객체 위에서 Lua 5.3(lupa)으로 실행한다.

    uv run tests/test_driver.py           # DP 매핑·설정 쓰기 계산·탐색·수명주기 (기기 없이)
    uv run tests/test_driver.py --live    # + 실제 기기에서 init → 조회 → 이벤트 발행까지

허브의 cosock/st.* 대신 tests/test_lua.py의 소켓·JSON 대역을 쓴다.
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
  local d = { id = "dev-1", label = "PV28-CW test", preferences = prefs, fields = {}, events = {}, timers = {} }
  function d:emit_event(ev) table.insert(self.events, ev) end
  function d:online() self.state = "online" end
  function d:offline() self.state = "offline" end
  function d:get_field(k) return self.fields[k] end
  function d:set_field(k, v) self.fields[k] = v end
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


def load_driver():
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
    end""")(T.PySock)
    g = lua.globals()
    g.JSON = lua.table_from({b"decode": lambda s: T.to_lua(json.loads(s))})
    g.SOCKET = socket_lib
    for mod in (b"init", b"dpmap", b"discovery"):
        lua.eval(f'function() package.loaded["{mod.decode()}"] = nil end')()
    cap = lua.execute(MOCKS)
    lua.eval('function() return require("init") end')()
    return cap


def prefs(**kw):
    base = {"ipAddress": "0.0.0.0", "deviceId": "-", "localKey": "-", "pollInterval": 30,
            "co2Alarm": 1500, "pm25Alarm": 75, "alarmSwitch": False, "screenSleep": True}
    base.update(kw)
    return T.to_lua(base)


def events_of(device) -> dict:
    out = {}
    for ev in device.events.values():
        arg = ev.arg
        out[f"{ev.cap.decode()}.{ev.attr.decode()}"] = (
            arg.value.decode() if isinstance(arg.value, bytes) else arg.value,
            arg.unit.decode() if arg.unit else None)
    return out


def test_dpmap() -> None:
    dpmap = lua.eval('require "dpmap"')
    # 2026-11-06 01:38 실기 값 (앱: PM2.5 7 / PM1.0 5 / PM10 8)
    dps = T.to_lua({"1": "normal", "2": 803, "14": "normal", "15": 100, "18": 20, "19": 61, "20": 7, "21": 115,
                    "22": 9, "101": 8, "102": 5, "106": "normal"})
    evs = {f"{e.cap.decode()}.{e.attr.decode()}": (e.value.decode() if isinstance(e.value, bytes) else e.value,
                                                   e.unit.decode() if e.unit else None)
           for e in dpmap.events(dps).values()}
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
    # 설정 쓰기: 바뀐 것만, 범위·단위 맞춤, 최초 생성(old 없음)은 무시
    w = dpmap.setting_writes(prefs(), prefs(co2Alarm=1234, screenSleep=False))
    T.check(dict(w.items()) == {b"26": 1200, b"108": False}, f"setting writes {dict(w.items())}")
    T.check(dpmap.setting_writes(prefs(), prefs()) is None, "no writes when unchanged")
    T.check(dpmap.setting_writes(lua.table_from({}), prefs(co2Alarm=900)) is None, "no writes on first prefs")
    T.check(dict(dpmap.setting_writes(prefs(), prefs(pm25Alarm=99)).items()) == {b"105": 75}, "pm25 clamp")


def test_lifecycle_unconfigured() -> None:
    cap = load_driver()
    drv = cap.driver
    T.check(drv.NAME == b"pv28cw-tuya-lan", "driver name")
    # 탐색: 기기가 없으면 자리표시자 생성, 설정 전 기기가 있으면 생성 안 함
    drv.discovery(drv, None, lambda: True)
    T.check(len(cap.created) == 1 and cap.created[1].type == b"LAN" and cap.created[1].profile == b"pv28cw-air-monitor",
            "discovery creates placeholder")
    d = cap.new_device(prefs())
    drv.devices[1] = d
    drv.discovery(drv, None, lambda: True)
    T.check(len(cap.created) == 1, "discovery skips while placeholder unconfigured")
    # 설정 전 기기: init → 타이머 2개, 조회 시 offline
    drv.lifecycle_handlers.init(drv, d)
    T.check(len(d.timers) == 2 and d.timers[1].interval == 30, "init schedules polling")
    T.check(len(d.events) == 1 and d.events[1].attr == b"supportedAirQualityValues", "init emits supported values")
    T.check(list(d.events[1].arg.values()) == [b"unknown", b"good", b"slightlyUnhealthy", b"unhealthy", b"veryUnhealthy"],
            "supported values match Matter sensor")
    cap.run_timers(d)
    T.check(d.state == b"offline" and len(d.events) == 1, "unconfigured device stays offline")


def test_lifecycle_live(ip: str) -> None:
    devices = json.loads((ROOT / "devices.json").read_text(encoding="utf-8"))
    dev = next(x for x in devices if x.get("product_id") == "yrr3eiyiacm31ski")
    cap = load_driver()
    drv = cap.driver
    d = cap.new_device(prefs())
    drv.devices[1] = d
    drv.lifecycle_handlers.init(drv, d)
    old = d.preferences
    # 사용자가 설정에 IP/ID/Key 입력 → infoChanged → 폴링 재시작
    d.preferences = prefs(ipAddress=ip, deviceId=dev["id"], localKey=dev["key"])
    drv.lifecycle_handlers.infoChanged(drv, d, b"infoChanged", lua.table_from({b"old_st_store": lua.table_from({b"preferences": old})}))
    T.check(d.timers[1].cancelled and len(d.timers) == 4, "infoChanged restarts polling")
    cap.run_timers(d)
    evs = {k: v for k, v in events_of(d).items() if not k.endswith("supportedAirQualityValues")}
    for k, v in sorted(evs.items()):
        print(f"    {k} = {v[0]!r}" + (f" {v[1]}" if v[1] else ""))
    T.check(d.state == b"online", "live device online")
    T.check(len(evs) == 11, f"live event count {len(evs)}")
    # refresh 명령
    n = len(d.events)
    drv.capability_handlers[b"refresh"][b"refresh"](drv, d)
    T.check(len(d.events) == n + 11, "refresh emits again")
    warns = [x.decode() for x in cap.logs.values() if x.startswith(b"warn")]
    T.check(not warns, f"no warnings: {warns}")


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--ip", default="192.168.0.7")
    args = ap.parse_args()
    for t in (test_dpmap, test_lifecycle_unconfigured):
        t()
        print(f"{t.__name__}: ok")
    if args.live:
        test_lifecycle_live(args.ip)
        print("test_lifecycle_live: ok")
    print(f"{T.passed} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
