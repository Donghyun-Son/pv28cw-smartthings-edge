-- PV28-CW (Tuya co2bj / yrr3eiyiacm31ski) DP → SmartThings capability 변환.
-- SmartThings 라이브러리에 의존하지 않는 순수 함수만 둔다 (tests/test_driver.py에서 직접 검증).
-- DP 표 근거: docs/development.md "DP" (2026-11-06 실기 관측, 앱 값 대조)

local M = {}

local UG = "μg/m^3"

-- 측정값 DP. scale이 있으면 value / scale 로 보낸다.
-- correction이 있으면 그 이름의 preference 값을 더하고 min~max로 자른다 (센서에 보정 DP가 없음).
M.MEASUREMENTS = {
  { dp = "2", cap = "carbonDioxideMeasurement", attr = "carbonDioxide", unit = "ppm" },
  { dp = "18", cap = "temperatureMeasurement", attr = "temperature", unit = "C" },
  { dp = "19", cap = "relativeHumidityMeasurement", attr = "humidity", unit = "%",
    correction = "humidityCorrection", min = 0, max = 100 },
  { dp = "20", cap = "fineDustSensor", attr = "fineDustLevel", unit = UG },
  { dp = "20", cap = "dustSensor", attr = "fineDustLevel", unit = UG },
  { dp = "101", cap = "dustSensor", attr = "dustLevel", unit = UG },
  { dp = "102", cap = "veryFineDustSensor", attr = "veryFineDustLevel", unit = UG }, -- 코드명은 pm25지만 실제 PM1.0
  -- 원시값 = μg/m³ (mg/m³ x1000). tvocMeasurement 단위는 ppm/ppb/ug/m3뿐이라 HCHO처럼 mg/m^3로 쓸 수 없다
  { dp = "21", cap = "tvocMeasurement", attr = "tvocLevel", unit = "ug/m3" },
  -- HCHO. formaldehydeMeasurement 단위는 ppm/mg/m^3뿐이다
  { dp = "22", cap = "formaldehydeMeasurement", attr = "formaldehydeLevel", unit = "mg/m^3", scale = 1000 },
  { dp = "15", cap = "battery", attr = "battery" },
}

-- 종합 공기질 등급은 같은 집의 Matter 공기질 센서(공식 matter-sensor 드라이버)와 같은 값만 쓴다.
M.SUPPORTED_AIR_QUALITY = { "unknown", "good", "slightlyUnhealthy", "unhealthy", "veryUnhealthy" }

-- 등급 순서 (뒤로 갈수록 나쁨)
local RANK = { good = 1, slightlyUnhealthy = 2, unhealthy = 3, veryUnhealthy = 4 }

-- 항목별 기준: { 상한, 등급 } 오름차순, 마지막 상한을 넘으면 마지막 등급.
-- 미세먼지는 환경부 예보 등급(좋음/보통/나쁨/매우나쁨) 경계, CO2·TVOC는 실내공기질 관리 기준을 참고했다.
-- 2단계(보통)는 Matter 센서와 맞춰 slightlyUnhealthy로 표시한다.
M.LEVELS = {
  pm25 = { { 15, "good" }, { 35, "slightlyUnhealthy" }, { 75, "unhealthy" }, { math.huge, "veryUnhealthy" } },
  pm10 = { { 30, "good" }, { 80, "slightlyUnhealthy" }, { 150, "unhealthy" }, { math.huge, "veryUnhealthy" } },
  co2 = { { 1000, "good" }, { 2000, "slightlyUnhealthy" }, { math.huge, "unhealthy" } },
  tvoc = { { 400, "good" }, { 1000, "slightlyUnhealthy" }, { math.huge, "unhealthy" } },
}

-- 종합 등급에 반영하는 항목. alarm_dp가 "alarm"이면 기기 자체 경보로 보고 최소 unhealthy.
local HEALTH_SOURCES = {
  { dp = "2", levels = "co2", alarm_dp = "1" },
  { dp = "20", levels = "pm25", alarm_dp = "106" },
  { dp = "102", levels = "pm25" },
  { dp = "101", levels = "pm10" },
  { dp = "21", levels = "tvoc" },
}

function M.level(kind, value)
  local table_ = M.LEVELS[kind]
  for _, step in ipairs(table_) do
    if value <= step[1] then return step[2] end
  end
  return table_[#table_][2]
end

local function worse(a, b)
  if a == nil then return b end
  return RANK[b] > RANK[a] and b or a
end

local function correction_of(m, prefs)
  return m.correction and prefs and tonumber(prefs[m.correction]) or 0
end

--- 보정 preference가 바뀌었는지. 바뀌면 바로 다시 조회해 보정한 값을 보낸다.
function M.corrections_changed(old_prefs, new_prefs)
  for _, m in ipairs(M.MEASUREMENTS) do
    if m.correction and correction_of(m, old_prefs) ~= correction_of(m, new_prefs) then return true end
  end
  return false
end

--- dps({["2"]=788, ...}), preferences → { {cap=, attr=, value=, unit=}, ... }
function M.events(dps, prefs)
  local out = {}
  for _, m in ipairs(M.MEASUREMENTS) do
    local v = dps[m.dp]
    if type(v) == "number" then
      if m.scale then v = v / m.scale end
      local c = correction_of(m, prefs)
      if c ~= 0 then
        v = math.max(m.min, math.min(m.max, v + c))
        v = math.tointeger(v) or v
      end
      out[#out + 1] = { cap = m.cap, attr = m.attr, value = v, unit = m.unit }
    end
  end
  local overall
  for _, h in ipairs(HEALTH_SOURCES) do
    local v = dps[h.dp]
    if type(v) == "number" then
      local lvl = M.level(h.levels, v)
      -- 기기 자체 경보(사용자가 기기에 설정한 임계값 초과)가 울리면 최소 unhealthy로 본다
      if h.alarm_dp and dps[h.alarm_dp] == "alarm" then lvl = worse(lvl, "unhealthy") end
      overall = worse(overall, lvl)
    end
  end
  if overall then
    out[#out + 1] = { cap = "airQualityHealthConcern", attr = "airQualityHealthConcern", value = overall }
  end
  return out
end

-- 기기 설정 preference → 쓰기 가능한 DP
M.SETTINGS = {
  co2Alarm = { dp = "26", min = 800, max = 2000, step = 100 },
  pm25Alarm = { dp = "105", min = 15, max = 75, step = 5 },
  alarmSwitch = { dp = "13", bool = true },
  screenSleep = { dp = "108", bool = true },
}

--- preference 값을 기기가 받는 DP 값으로 바꾼다.
-- 숫자 설정은 목록(enumeration) 문자열로 오지만, 예전 정수 설정 값도 범위·단위에 맞춰 받는다.
function M.setting_value(spec, value)
  if spec.bool then return value == true end
  local v = math.tointeger(math.floor((tonumber(value) or spec.min) / spec.step + 0.5) * spec.step)
  return math.max(spec.min, math.min(spec.max, v))
end

--- 바뀐 설정 preference만 골라 { [dp] = 값 } 으로 돌려준다. 이전 값이 없으면(최초 생성) 쓰지 않는다.
function M.setting_writes(old_prefs, new_prefs)
  local writes, any = {}, false
  for name, spec in pairs(M.SETTINGS) do
    local old, new = old_prefs[name], new_prefs[name]
    if old ~= nil and new ~= nil then
      local value = M.setting_value(spec, new)
      if value ~= M.setting_value(spec, old) then
        writes[spec.dp] = value
        any = true
      end
    end
  end
  return any and writes or nil
end

return M
