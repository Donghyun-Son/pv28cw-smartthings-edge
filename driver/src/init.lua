-- PV28-CW 공기질 센서 SmartThings Edge LAN 드라이버 (Tuya 프로토콜 3.5).
-- 주기마다 연결 → 세션 키 협상 → (대기 중인 설정 쓰기) → DP 조회 → 종료. 연결을 붙잡아 두지 않는다.

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
local INITIALIZED = "initialized"
local PENDING_WRITES = "pending_writes" -- 아직 센서에 쓰지 못한 설정 { [dp] = 값 }
local DEFAULT_INTERVAL = 30
local OFFLINE_AFTER = 3 -- 연속 실패 횟수
local CONNECTION_PREFS = { "ipAddress", "localKey", "pollInterval" }

local function name_of(device)
  return device.label or device.id
end

--- 연결 설정이 없거나 잘못됐으면 어느 항목인지 남기고 offline으로 둔다.
local function connection_or_offline(device)
  local conn, problem = discovery.connection(device)
  if not conn then
    log.info(string.format("%s: 설정에서 %s를 확인하세요", name_of(device), problem))
    device:offline()
  end
  return conn
end

local function client_for(conn)
  return Client.new({
    ip = conn.ip,
    local_key = conn.local_key,
    socket = cosock.socket,
    json = json,
    log = log,
  })
end

--- 바뀐 값만 보낸다. 같은 값을 주기마다 보내면 허브→클라우드 이벤트만 늘어난다.
local function emit_changes(device, events)
  for _, ev in ipairs(events) do
    if device:get_latest_state("main", ev.cap, ev.attr) ~= ev.value then
      local ok, err = pcall(function()
        local attr = capabilities[ev.cap][ev.attr]
        device:emit_event(attr(ev.unit and { value = ev.value, unit = ev.unit } or { value = ev.value }))
      end)
      if not ok then log.warn(string.format("%s: %s.%s 이벤트 실패: %s", name_of(device), ev.cap, ev.attr, err)) end
    end
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

--- 한 세션 안에서 대기 중인 설정을 쓰고 DPS를 조회한다.
-- 쓰기가 성공했거나, 쓰기는 실패했지만 조회는 됐으면(기기가 받지 않는 것) 대기 목록을 비운다.
-- 연결이 끊겨 둘 다 실패했을 때만 남겨 두고 다음 조회 때 다시 보낸다.
local function sync(device, client)
  local pending = device:get_field(PENDING_WRITES)
  local wrote, werr
  if pending then wrote, werr = client:control(pending) end
  local dps, err = client:query()
  if pending and (wrote or dps) then
    device:set_field(PENDING_WRITES, nil, { persist = true })
    if wrote then
      log.info(name_of(device) .. ": 센서 설정을 썼습니다")
    else
      log.warn(name_of(device) .. ": 센서 설정 쓰기 실패: " .. tostring(werr))
    end
  end
  return dps, err
end

local function record_failure(device, err)
  local failures = (device:get_field(FAILURES) or 0) + 1
  device:set_field(FAILURES, failures)
  -- 오프라인이 된 뒤에는 같은 경고가 주기마다 쌓이지 않게 debug로 남긴다
  local write_log = failures > OFFLINE_AFTER and log.debug or log.warn
  write_log(string.format("%s: 조회 실패 %d회: %s", name_of(device), failures, tostring(err)))
  if failures >= OFFLINE_AFTER then device:offline() end
end

local function poll(device)
  local conn = connection_or_offline(device)
  if not conn then return end
  local client = client_for(conn)
  local dps, err = client:session(function() return sync(device, client) end)
  -- 응답은 왔지만 측정값이 하나도 없으면(센서 MCU 멈춤 등) 실패로 센다
  local events = dps and dpmap.events(dps, device.preferences)
  if not events or #events == 0 then
    record_failure(device, err or "응답에 측정값이 없음")
    return
  end
  if (device:get_field(FAILURES) or 0) >= OFFLINE_AFTER then
    log.info(name_of(device) .. ": 다시 연결됨")
  end
  device:set_field(FAILURES, 0)
  device:online()
  emit_changes(device, events)
end

local function start_polling(device)
  local old = device:get_field(POLL_TIMER)
  if old then
    device.thread:cancel_timer(old)
    device:set_field(POLL_TIMER, nil)
  end
  -- 설정 전에는 조회하지 않는다. 연결 설정이 바뀌면 infoChanged가 다시 부른다
  if not connection_or_offline(device) then return end
  local interval = math.max(10, tonumber(device.preferences.pollInterval) or DEFAULT_INTERVAL)
  local timer = device.thread:call_on_schedule(interval, function() poll(device) end, "pv28cw poll")
  device:set_field(POLL_TIMER, timer)
  device.thread:call_with_delay(2, function() poll(device) end, "pv28cw first poll")
  log.info(string.format("%s: %d초마다 조회", name_of(device), interval))
end

-- init과 added 중 먼저 온 쪽에서 한 번만 준비한다.
-- LAN 드라이버에서 init이 호출되지 않는 경우가 있어 added에서도 부른다 (공식 WeMo 드라이버 주석)
local function initialize(_, device)
  if device:get_field(INITIALIZED) then return end
  device:set_field(INITIALIZED, true)
  emit_supported_values(device)
  start_polling(device)
end

local function device_removed(_, device)
  local timer = device:get_field(POLL_TIMER)
  if timer then device.thread:cancel_timer(timer) end
end

local function info_changed(_, device, _, args)
  local old = (args and args.old_st_store and args.old_st_store.preferences) or {}
  local new = device.preferences

  -- 센서 설정은 대기 목록에 넣고 다음 조회 때 함께 쓴다
  local writes = dpmap.setting_writes(old, new)
  if writes then
    local pending = device:get_field(PENDING_WRITES) or {}
    for dp, value in pairs(writes) do pending[dp] = value end
    device:set_field(PENDING_WRITES, pending, { persist = true })
  end

  for _, key in ipairs(CONNECTION_PREFS) do
    if old[key] ~= new[key] then
      device:set_field(FAILURES, 0)
      start_polling(device) -- 2초 뒤 첫 조회에서 대기 중인 설정도 쓴다
      return
    end
  end
  -- 설정 쓰기나 보정 값 변경은 다음 주기를 기다리지 않고 바로 반영한다
  if writes or dpmap.corrections_changed(old, new) then poll(device) end
end

local function refresh(_, device)
  poll(device)
end

local driver = Driver("pv28cw-tuya-lan", {
  discovery = discovery.handle,
  lifecycle_handlers = {
    init = initialize,
    added = initialize,
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
