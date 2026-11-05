-- Tuya 3.5 LAN 클라이언트: 연결 → 세션 키 협상 → 조회/제어 → 종료.
-- SmartThings 밖에서도 돌도록 소켓 라이브러리와 JSON 디코더를 주입받는다.
--   opts.socket : cosock.socket 또는 luasocket 호환 (tcp, settimeout, connect, send, receive, close)
--   opts.json   : decode(str) 를 가진 모듈 (st.json)
-- 3.4부터는 요청에 Device ID가 들어가지 않아서 받지 않는다 (tinytuya payload_dict "v3.4"/"v3.5").

local protocol = require "tuya.protocol"

local CMD = protocol.CMD

local Client = {}
Client.__index = Client

math.randomseed(os.time() + math.floor(os.clock() * 1e6))

local function random_bytes(n)
  local t = {}
  for i = 1, n do t[i] = math.random(0, 255) end
  return string.char(table.unpack(t))
end

function Client.new(opts)
  assert(opts.ip and opts.local_key, "ip, local_key required")
  assert(#opts.local_key == 16, "local key must be 16 characters")
  return setmetatable({
    ip = opts.ip,
    port = opts.port or 6668,
    local_key = opts.local_key,
    socket = assert(opts.socket, "socket library required"),
    json = assert(opts.json, "json library required"),
    timeout = opts.timeout or 5,
    log = opts.log,
    seqno = 1,
  }, Client)
end

function Client:_debug(fmt, ...)
  if self.log then self.log.debug(string.format("[tuya %s] " .. fmt, self.ip, ...)) end
end

function Client:_send(cmd, payload, key)
  local frame = protocol.pack(self.seqno, cmd, payload, key, random_bytes(12))
  self.seqno = self.seqno + 1
  local ok, err = self.sock:send(frame)
  if not ok then return nil, "send: " .. tostring(err) end
  return true
end

function Client:_recv_exact(n)
  local data, err = self.sock:receive(n)
  if not data then return nil, "receive: " .. tostring(err) end
  return data
end

--- 프레임 하나를 읽어 복호화한다. 접두사가 어긋나 있으면 한 바이트씩 버리며 맞춘다.
function Client:_recv_frame(key)
  local head, err = self:_recv_exact(4)
  if not head then return nil, err end
  local skipped = 0
  while head ~= protocol.PREFIX do
    local b, e = self:_recv_exact(1)
    if not b then return nil, e end
    head = head:sub(2) .. b
    skipped = skipped + 1
    if skipped > 4096 then return nil, "frame prefix not found" end
  end
  local rest, err2 = self:_recv_exact(protocol.HEADER_LEN - 4)
  if not rest then return nil, err2 end
  local header = head .. rest
  local seqno, cmd_or_err, total = protocol.parse_header(header)
  if not seqno then return nil, cmd_or_err end
  local tail, err3 = self:_recv_exact(total - protocol.HEADER_LEN)
  if not tail then return nil, err3 end
  return protocol.unpack(header .. tail, key)
end

function Client:close()
  if self.sock then
    self.sock:close()
    self.sock = nil
  end
  self.session_key = nil
end

--- TCP 연결 후 세션 키를 협상한다.
function Client:connect()
  self:close()
  local sock, err = self.socket.tcp()
  if not sock then return nil, "tcp: " .. tostring(err) end
  sock:settimeout(self.timeout)
  local ok, cerr = sock:connect(self.ip, self.port)
  if not ok then
    sock:close()
    return nil, "connect: " .. tostring(cerr)
  end
  self.sock = sock
  self.seqno = 1

  local local_nonce = random_bytes(16)
  local sent, serr = self:_send(CMD.SESS_KEY_NEG_START, local_nonce, self.local_key)
  if not sent then self:close() return nil, serr end
  local resp, rerr = self:_recv_frame(self.local_key)
  if not resp then
    self:close()
    -- local key가 틀리면 기기 응답의 GCM 태그 검증에서 실패한다
    return nil, "negotiate: " .. tostring(rerr)
  end
  if resp.cmd ~= CMD.SESS_KEY_NEG_RESP then
    self:close()
    return nil, "negotiate: unexpected cmd " .. resp.cmd
  end
  local finish, session_key = protocol.finish_negotiation(self.local_key, local_nonce, resp.payload)
  if not finish then self:close() return nil, session_key end
  sent, serr = self:_send(CMD.SESS_KEY_NEG_FINISH, finish, self.local_key)
  if not sent then self:close() return nil, serr end
  if session_key:byte(1) == 0 then
    -- 첫 바이트가 0x00인 세션 키는 기기가 거부한다는 보고가 있어 새로 협상한다 (tinytuya Discussion #260)
    self:close()
    return nil, "zero session key"
  end
  self.session_key = session_key
  self:_debug("session established")
  return true
end

function Client:_decode(payload)
  if payload == "" then return nil end
  local ok, data = pcall(self.json.decode, payload)
  if not ok or type(data) ~= "table" then
    self:_debug("undecodable payload %q", payload:sub(1, 80))
    return nil
  end
  return data
end

--- 응답 프레임을 읽으며 DPS를 모은다. want_cmd에 대한 응답이 오면 끝낸다.
function Client:_read_reply(want_cmd)
  local dps = {}
  for _ = 1, 8 do
    local frame, err = self:_recv_frame(self.session_key)
    if not frame then return nil, err end
    local data = self:_decode(frame.payload)
    local frame_dps = data and (data.dps or (type(data.data) == "table" and data.data.dps))
    if type(frame_dps) == "table" then
      for k, v in pairs(frame_dps) do dps[tostring(k)] = v end
    end
    self:_debug("frame cmd=%d retcode=%d %s", frame.cmd, frame.retcode, frame.payload:sub(1, 200))
    if frame.cmd == want_cmd then
      if frame.retcode ~= 0 then return nil, "retcode " .. frame.retcode end
      return dps
    end
  end
  return nil, "no reply to cmd " .. want_cmd
end

--- 현재 DPS 전체를 조회한다 (session 안에서).
function Client:query()
  local ok, err = self:_send(CMD.DP_QUERY_NEW, "{}", self.session_key)
  if not ok then return nil, err end
  return self:_read_reply(CMD.DP_QUERY_NEW)
end

--- DPS를 쓴다 (session 안에서). dps = { ["26"] = 1200, ... }
function Client:control(dps)
  local payload = protocol.control_payload(dps, os.time())
  local ok, err = self:_send(CMD.CONTROL_NEW, payload, self.session_key)
  if not ok then return nil, err end
  return self:_read_reply(CMD.CONTROL_NEW)
end

--- 연결 → fn() → 종료. fn 안에서 query/control을 부르고, fn이 돌려준 값과 오류를 그대로 돌려준다.
-- 중간에 Lua 에러가 나도 소켓을 닫고 nil, 이유로 바꿔 돌려준다.
function Client:session(fn)
  local ok, result, err = pcall(function()
    local connected, cerr
    for _ = 1, 2 do
      connected, cerr = self:connect()
      if connected or cerr ~= "zero session key" then break end
    end
    if not connected then return nil, cerr end
    return fn()
  end)
  self:close()
  if not ok then return nil, "lua error: " .. tostring(result) end
  return result, err
end

return Client
