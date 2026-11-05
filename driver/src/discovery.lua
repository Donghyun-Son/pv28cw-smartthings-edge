-- 허브는 Tuya 탐색 포트(UDP 6666/6667/7000)를 bind할 수 없어서 기기를 스스로 찾지 못한다.
-- "주변 기기 검색" 때 설정 전 자리표시자 기기를 하나 만들고, 사용자가 설정에서 IP와 Local Key를 넣는다.

local log = require "log"

local M = {}

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

function M.handle(driver, _opts, _should_continue)
  for _, device in ipairs(driver:get_devices()) do
    if not M.connection(device) then
      log.info("discovery: 설정 전인 기기가 이미 있음: " .. tostring(device.label))
      return
    end
  end
  local dni = string.format("pv28cw-%d-%04d", os.time(), math.random(0, 9999))
  log.info("discovery: 자리표시자 기기 생성 " .. dni)
  driver:try_create_device({
    type = "LAN",
    device_network_id = dni,
    label = "공기질 센서",
    profile = "pv28cw-air-monitor",
    manufacturer = "Tuya",
    model = "PV28-CW",
    vendor_provided_label = "PV28-CW",
  })
end

return M
