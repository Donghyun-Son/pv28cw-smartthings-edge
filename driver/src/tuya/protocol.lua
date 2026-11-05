-- Tuya LAN 프로토콜 3.5 프레임 (6699 접두사, AES-128-GCM).
-- 기준: tinytuya 1.20.0 core/message_helper.py, core/XenonDevice.py
--
--   header(18) = 00006699 | 0000 | seqno(4) | cmd(4) | length(4)
--   body       = iv(12) | ciphertext | tag(16)        length = #body
--   suffix(4)  = 00009966
--   AAD        = header[5..18] (접두사 뒤 14바이트)
-- 기기가 보낸 평문은 retcode(4)로 시작하고, 그 뒤에 "3.5"+0x00*12 헤더가 붙을 수 있다.

local gcm = require "tuya.gcm"
local sha256 = require "tuya.sha256"

local M = {}

M.PREFIX = "\0\0\x66\x99"
M.SUFFIX = "\0\0\x99\x66"
M.HEADER_LEN = 18
M.MAX_LENGTH = 1000 * 16

M.CMD = {
  SESS_KEY_NEG_START = 0x03,
  SESS_KEY_NEG_RESP = 0x04,
  SESS_KEY_NEG_FINISH = 0x05,
  CONTROL_NEW = 0x0d,
  DP_QUERY_NEW = 0x10,
}

local VERSION_HEADER = "3.5" .. string.rep("\0", 12)

-- 버전 헤더를 붙이지 않는 명령 (tinytuya header.NO_PROTOCOL_HEADER_CMDS)
local NO_VERSION_HEADER = {
  [0x03] = true, [0x04] = true, [0x05] = true, [0x09] = true,
  [0x0a] = true, [0x10] = true, [0x12] = true, [0x40] = true,
}

--- 클라이언트 → 기기 프레임을 만든다.
function M.pack(seqno, cmd, payload, key, iv)
  if not NO_VERSION_HEADER[cmd] then payload = VERSION_HEADER .. payload end
  local header = string.pack(">I4I2I4I4I4", 0x6699, 0, seqno, cmd, #payload + 12 + 16)
  local ct, tag = gcm.encrypt(key, iv, payload, header:sub(5))
  return header .. iv .. ct .. tag .. M.SUFFIX
end

--- 18바이트 헤더를 해석한다. seqno, cmd, 프레임 전체 길이를 돌려준다.
function M.parse_header(header)
  local prefix, _, seqno, cmd, length = string.unpack(">I4I2I4I4I4", header)
  if prefix ~= 0x6699 then return nil, "bad prefix" end
  if length < 28 or length > M.MAX_LENGTH then return nil, "bad length " .. length end
  return seqno, cmd, M.HEADER_LEN + length + #M.SUFFIX
end

--- 기기 → 클라이언트 프레임 하나를 복호화한다.
-- 성공하면 { seqno, cmd, retcode, payload }, 실패하면 nil, 이유.
function M.unpack(frame, key)
  local seqno, cmd = M.parse_header(frame)
  if not seqno then return nil, cmd end
  if frame:sub(-4) ~= M.SUFFIX then return nil, "bad suffix" end
  local body = frame:sub(M.HEADER_LEN + 1, -5)
  local iv, ct, tag = body:sub(1, 12), body:sub(13, -17), body:sub(-16)
  local plain, err = gcm.decrypt(key, iv, ct, frame:sub(5, M.HEADER_LEN), tag)
  if not plain then return nil, err end
  local retcode = 0
  if #plain >= 4 then
    retcode = string.unpack(">I4", plain)
    plain = plain:sub(5)
  end
  if plain:sub(1, 3) == "3.5" then plain = plain:sub(#VERSION_HEADER + 1) end
  return { seqno = seqno, cmd = cmd, retcode = retcode, payload = plain }
end

--- 세션 키 협상 3단계: 기기의 cmd 4 응답을 검증하고 cmd 5 페이로드와 세션 키를 만든다.
-- resp_payload = remote_nonce(16) | HMAC(local_key, local_nonce)(32)
function M.finish_negotiation(local_key, local_nonce, resp_payload)
  if #resp_payload < 48 then return nil, "short negotiation response" end
  local remote_nonce = resp_payload:sub(1, 16)
  if resp_payload:sub(17, 48) ~= sha256.hmac(local_key, local_nonce) then
    return nil, "negotiation HMAC mismatch (wrong local key?)"
  end
  local finish = sha256.hmac(local_key, remote_nonce)
  -- 3.5 세션 키 = GCM(local_key, iv=local_nonce[1..12]) 로 암호화한 (local_nonce XOR remote_nonce)
  local session_key = gcm.encrypt(local_key, local_nonce:sub(1, 12), gcm.xor(local_nonce, remote_nonce), "")
  return finish, session_key
end

local function json_string(s)
  return '"' .. s:gsub('[%c"\\]', function(c)
    return string.format("\\u%04x", c:byte())
  end) .. '"'
end

--- CONTROL_NEW 페이로드: {"protocol":5,"t":<int>,"data":{"dps":{...}}} (공백 없이)
function M.control_payload(dps, now)
  local parts = {}
  for dp, value in pairs(dps) do
    local v
    local tv = type(value)
    if tv == "boolean" then
      v = value and "true" or "false"
    elseif tv == "number" then
      v = math.type(value) == "integer" and tostring(value) or string.format("%.17g", value)
    else
      v = json_string(tostring(value))
    end
    parts[#parts + 1] = json_string(tostring(dp)) .. ":" .. v
  end
  table.sort(parts)
  return string.format('{"protocol":5,"t":%d,"data":{"dps":{%s}}}', now, table.concat(parts, ","))
end

return M
