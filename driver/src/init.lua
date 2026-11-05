-- PV28-CW 공기질 센서 SmartThings Edge LAN 드라이버 (Tuya 프로토콜 3.5).
-- 주기마다 연결 → 세션 키 협상 → DP 조회 → 종료. 연결을 붙잡아 두지 않는다.

local Driver = require "st.driver"
local capabilities = require "st.capabilities"
local cosock = require "cosock"
local json = require "st.json"
local log = require "log"

local Client = require "tuya.client"
local dpmap = require "dpmap"
local discovery = require "discovery"

local POLL_TIMER = "poll_timer"
local FAILURES = "poll_failures"
local DEFAULT_INTERVAL = 30
local OFFLINE_AFTER = 3 -- 연속 실패 횟수
local CONNECTION_PREFS = { "ipAddress", "deviceId", "localKey", "pollInterval" }

local function name_of(device)
  return device.label or device.id
end

local function client_for(device)
  local p = device.preferences
  return Client.new({
    ip = p.ipAddress,
    device_id = p.deviceId,
    local_key = p.localKey,
    socket = cosock.socket,
    json = json,
    log = log,
    timeout = 5,
  })
end

local function emit_dps(device, dps)
  for _, ev in ipairs(dpmap.events(dps)) do
    local ok, err = pcall(function()
      local attr = capabilities[ev.cap][ev.attr]
      device:emit_event(attr(ev.unit and { value = ev.value, unit = ev.unit } or { value = ev.value }))
    end)
    if not ok then log.warn(string.format("%s: %s.%s 이벤트 실패: %s", name_of(device), ev.cap, ev.attr, err)) end
  end
end

-- 앱이 보여 줄 종합 등급 범위를 Matter 공기질 센서와 같게 제한한다
local function emit_supported_values(device)
  local ok, err = pcall(function()
    device:emit_event(capabilities.airQualityHealthConcern.supportedAirQualityValues(
      dpmap.SUPPORTED_AIR_QUALITY, { visibility = { displayed = false } }))
  end)
  if not ok then log.warn(name_of(device) .. ": supportedAirQualityValues 실패: " .. tostring(err)) end
end

local function poll(device)
  if not discovery.is_configured(device) then
    log.info(name_of(device) .. ": 설정에서 IP 주소, Device ID, Local Key를 입력하세요")
    device:offline()
    return
  end
  local dps, err = client_for(device):fetch()
  if not dps then
    local failures = (device:get_field(FAILURES) or 0) + 1
    device:set_field(FAILURES, failures)
    log.warn(string.format("%s: 조회 실패 %d회: %s", name_of(device), failures, tostring(err)))
    if failures >= OFFLINE_AFTER then device:offline() end
    return
  end
  device:set_field(FAILURES, 0)
  device:online()
  emit_dps(device, dps)
end

local function start_polling(device)
  local old = device:get_field(POLL_TIMER)
  if old then device.thread:cancel_timer(old) end
  local interval = math.max(10, tonumber(device.preferences.pollInterval) or DEFAULT_INTERVAL)
  local timer = device.thread:call_on_schedule(interval, function() poll(device) end, "pv28cw poll")
  device:set_field(POLL_TIMER, timer)
  device.thread:call_with_delay(2, function() poll(device) end, "pv28cw first poll")
  log.info(string.format("%s: %d초마다 조회", name_of(device), interval))
end

local function device_init(_, device)
  emit_supported_values(device)
  start_polling(device)
end

local function device_added(_, device)
  emit_supported_values(device)
  -- LAN 드라이버에서 init이 호출되지 않는 경우가 있어 added에서도 보장한다 (공식 WeMo 드라이버 주석)
  if not device:get_field(POLL_TIMER) then start_polling(device) end
end

local function device_removed(_, device)
  local timer = device:get_field(POLL_TIMER)
  if timer then device.thread:cancel_timer(timer) end
end

local function info_changed(_, device, _, args)
  local old = (args and args.old_st_store and args.old_st_store.preferences) or {}
  local new = device.preferences

  local writes = dpmap.setting_writes(old, new)
  if writes and discovery.is_configured(device) then
    local dps, err = client_for(device):apply(writes)
    if dps then
      emit_dps(device, dps)
    else
      log.warn(name_of(device) .. ": 설정 쓰기 실패: " .. tostring(err))
    end
  end

  for _, key in ipairs(CONNECTION_PREFS) do
    if old[key] ~= new[key] then
      device:set_field(FAILURES, 0)
      start_polling(device)
      break
    end
  end
end

local function refresh(_, device)
  poll(device)
end

local driver = Driver("pv28cw-tuya-lan", {
  discovery = discovery.handle,
  lifecycle_handlers = {
    init = device_init,
    added = device_added,
    infoChanged = info_changed,
    removed = device_removed,
  },
  capability_handlers = {
    [capabilities.refresh.ID] = {
      [capabilities.refresh.commands.refresh.NAME] = refresh,
    },
  },
  -- 블로킹 소켓 수신이 다른 기기를 멈추지 않도록 기기별 스레드를 쓴다
  shared_device_thread_enabled = false,
})

driver:run()
