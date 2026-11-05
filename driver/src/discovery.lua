-- 허브는 Tuya 탐색 포트(UDP 6666/6667/7000)를 bind할 수 없어서 기기를 스스로 찾지 못한다.
-- "주변 기기 검색" 때 설정 전 자리표시자 기기를 하나 만들고, 사용자가 설정에서 IP/ID/Key를 넣는다.

local log = require "log"

local M = {}

--- IP, Device ID, Local Key가 모두 들어 있는지.
function M.is_configured(device)
  local p = device.preferences or {}
  return type(p.ipAddress) == "string" and p.ipAddress:match("^%d+%.%d+%.%d+%.%d+$") ~= nil
    and p.ipAddress ~= "0.0.0.0"
    and type(p.deviceId) == "string" and #p.deviceId >= 20
    and type(p.localKey) == "string" and #p.localKey == 16
end

function M.handle(driver, _opts, _should_continue)
  for _, device in ipairs(driver:get_devices()) do
    if not M.is_configured(device) then
      log.info("discovery: 설정 전인 기기가 이미 있음: " .. tostring(device.label))
      return
    end
  end
  local dni = string.format("pv28cw-%d-%04d", os.time(), math.random(0, 9999))
  log.info("discovery: 자리표시자 기기 생성 " .. dni)
  driver:try_create_device({
    type = "LAN",
    device_network_id = dni,
    label = "PV28-CW 공기질 측정기",
    profile = "pv28cw-air-monitor",
    manufacturer = "Tuya",
    model = "PV28-CW",
    vendor_provided_label = "PV28-CW",
  })
end

return M
