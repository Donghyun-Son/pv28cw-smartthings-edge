-- 허브는 Tuya 탐색 포트(UDP 6666/6667/7000)를 bind할 수 없어서 기기를 스스로 찾지 못한다.
-- 처음 "주변 기기 검색" 때와 기기 설정의 "새 기기 추가" 때 설정 전 자리표시자 기기를 하나 만들고,
-- 사용자가 설정에서 IP와 Local Key를 넣는다.

local log = require "log"

local M = {}

local BASE_LABEL = "공기질 센서"
-- try_create_device는 비동기라 만든 기기가 get_devices에 바로 나오지 않는다.
-- 그 사이에 다시 요청해도(스위치를 껐다가 바로 다시 켬 등) 하나만 만들도록 이 시간 동안 기다린다
local PENDING_SECONDS = 60
local pending -- { dni =, at = } 만들기를 요청했지만 아직 get_devices에 나오지 않은 기기

local function trim(s)
  if type(s) ~= "string" then return nil end
  return (s:gsub("^%s+", ""):gsub("%s+$", ""))
end

local function valid_ip(ip)
  local octets = { (ip or ""):match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$") }
  if #octets ~= 4 or ip == "0.0.0.0" then return false end
  for _, n in ipairs(octets) do
    if tonumber(n) > 255 then return false end
  end
  return true
end

--- 설정에서 연결 정보를 읽는다. 복사할 때 딸려 온 앞뒤 공백은 무시한다.
-- 성공하면 { ip, local_key }, 아니면 nil과 잘못된 항목 이름.
function M.connection(device)
  local p = device.preferences or {}
  local ip, key = trim(p.ipAddress), trim(p.localKey)
  if not valid_ip(ip) then return nil, "IP 주소" end
  if not key or #key ~= 16 then return nil, "Local Key(16자)" end
  return { ip = ip, local_key = key }
end

-- 기기가 여러 대일 때 구분되게 "공기질 센서", "공기질 센서 2", ... 중 안 쓰는 이름
local function next_label(devices)
  local used = {}
  for _, device in ipairs(devices) do used[device.label or ""] = true end
  if not used[BASE_LABEL] then return BASE_LABEL end
  local n = 2
  while used[BASE_LABEL .. " " .. n] do n = n + 1 end
  return BASE_LABEL .. " " .. n
end

--- 설정 전 자리표시자 기기를 하나 만든다. 만들었으면 true.
-- 설정 전 기기가 이미 있거나 방금 만든 기기가 아직 추가되는 중이면 만들지 않는다.
function M.add_placeholder(driver)
  local devices = driver:get_devices()
  for _, device in ipairs(devices) do
    if pending and device.device_network_id == pending.dni then pending = nil end
    if not M.connection(device) then
      log.info("새 기기 추가: 설정 전인 기기가 이미 있어서 만들지 않음: " .. tostring(device.label))
      return false
    end
  end
  if pending and os.time() - pending.at < PENDING_SECONDS then
    log.info("새 기기 추가: 방금 만든 기기가 아직 추가되는 중이라 만들지 않음")
    return false
  end
  local dni = string.format("pv28cw-%d-%04d", os.time(), math.random(0, 9999))
  local label = next_label(devices)
  log.info(string.format("새 기기 추가: %s (%s)", label, dni))
  pending = { dni = dni, at = os.time() }
  driver:try_create_device({
    type = "LAN",
    device_network_id = dni,
    label = label,
    profile = "pv28cw-air-monitor",
    manufacturer = "Tuya",
    model = "PV28-CW",
    vendor_provided_label = "PV28-CW",
  })
  return true
end

-- 주변 기기 검색은 앱에서 다른 기기를 찾을 때도 허브의 모든 드라이버에 불린다.
-- 그래서 기기가 하나도 없을 때(처음 설치)만 만들고, 두 번째부터는 기기 설정의 "새 기기 추가"로 만든다
function M.handle(driver, _opts, _should_continue)
  if #driver:get_devices() > 0 then
    log.debug("discovery: 기기가 이미 있어서 만들지 않음 (추가는 기기 설정의 새 기기 추가)")
    return
  end
  M.add_placeholder(driver)
end

return M
