-- AES-128 블록 암호화 (암호화 방향만). Tuya 3.5는 GCM(CTR)만 쓰므로 복호화 블록 연산이 필요 없다.
-- Lua 5.3 정수 비트 연산 사용.

local M = {}

local XTIME = {}
for i = 0, 255 do
  local x = i << 1
  if x & 0x100 ~= 0 then x = x ~ 0x11B end
  XTIME[i] = x
end

-- S-box를 GF(2^8) 역원 + 아핀 변환으로 생성 (상수표 오타 방지)
local SBOX = {}
do
  local function rotl8(x, s) return ((x << s) | (x >> (8 - s))) & 0xFF end
  local p, q = 1, 1
  repeat
    p = (p ~ (p << 1) ~ ((p & 0x80) ~= 0 and 0x1B or 0)) & 0xFF
    q = q ~ (q << 1)
    q = q ~ (q << 2)
    q = q ~ (q << 4)
    q = q & 0xFF
    if q & 0x80 ~= 0 then q = q ~ 0x09 end
    SBOX[p] = (q ~ rotl8(q, 1) ~ rotl8(q, 2) ~ rotl8(q, 3) ~ rotl8(q, 4) ~ 0x63) & 0xFF
  until p == 1
  SBOX[0] = 0x63
end

--- 16바이트 키를 176바이트 라운드 키 배열로 확장한다.
function M.expand_key(key)
  assert(#key == 16, "AES-128 key must be 16 bytes")
  local w = { key:byte(1, 16) }
  local rcon = 1
  for i = 17, 176, 4 do
    local t1, t2, t3, t4 = w[i - 4], w[i - 3], w[i - 2], w[i - 1]
    if (i - 1) % 16 == 0 then
      t1, t2, t3, t4 = SBOX[t2] ~ rcon, SBOX[t3], SBOX[t4], SBOX[t1]
      rcon = XTIME[rcon]
    end
    w[i] = w[i - 16] ~ t1
    w[i + 1] = w[i - 15] ~ t2
    w[i + 2] = w[i - 14] ~ t3
    w[i + 3] = w[i - 13] ~ t4
  end
  return w
end

--- 확장 키 w로 16바이트 블록 하나를 암호화한다.
function M.encrypt_block(w, block)
  local s = { block:byte(1, 16) }
  for i = 1, 16 do s[i] = s[i] ~ w[i] end
  local t = {}
  for round = 1, 10 do
    -- SubBytes + ShiftRows (state[r + 4c], 열 우선)
    for c = 0, 3 do
      for r = 0, 3 do
        t[r + 4 * c + 1] = SBOX[s[r + 4 * ((c + r) % 4) + 1]]
      end
    end
    if round < 10 then
      for c = 0, 12, 4 do
        local a0, a1, a2, a3 = t[c + 1], t[c + 2], t[c + 3], t[c + 4]
        local x = a0 ~ a1 ~ a2 ~ a3
        t[c + 1] = a0 ~ x ~ XTIME[a0 ~ a1]
        t[c + 2] = a1 ~ x ~ XTIME[a1 ~ a2]
        t[c + 3] = a2 ~ x ~ XTIME[a2 ~ a3]
        t[c + 4] = a3 ~ x ~ XTIME[a3 ~ a0]
      end
    end
    local off = round * 16
    for i = 1, 16 do s[i] = t[i] ~ w[off + i] end
  end
  return string.char(table.unpack(s))
end

return M
