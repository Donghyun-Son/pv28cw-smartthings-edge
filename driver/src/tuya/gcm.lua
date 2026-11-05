-- AES-128-GCM (NIST SP 800-38D), 12바이트 IV 전용.
-- GHASH는 128비트 값을 64비트 정수 두 개(hi, lo)로 다룬다. Lua 5.3의 >>는 논리 시프트다.

local aes = require "tuya.aes"

local M = {}

local R = 0xE1 << 56

local function gmul(xh, xl, hh, hl)
  local zh, zl = 0, 0
  local vh, vl = hh, hl
  for i = 63, 0, -1 do
    if (xh >> i) & 1 == 1 then zh, zl = zh ~ vh, zl ~ vl end
    local lsb = vl & 1
    vl = (vl >> 1) | ((vh & 1) << 63)
    vh = vh >> 1
    if lsb == 1 then vh = vh ~ R end
  end
  for i = 63, 0, -1 do
    if (xl >> i) & 1 == 1 then zh, zl = zh ~ vh, zl ~ vl end
    local lsb = vl & 1
    vl = (vl >> 1) | ((vh & 1) << 63)
    vh = vh >> 1
    if lsb == 1 then vh = vh ~ R end
  end
  return zh, zl
end

local function ghash(hh, hl, aad, ct)
  local yh, yl = 0, 0
  local function absorb(data)
    for i = 1, #data, 16 do
      local blk = data:sub(i, i + 15)
      if #blk < 16 then blk = blk .. string.rep("\0", 16 - #blk) end
      local bh, bl = string.unpack(">i8i8", blk)
      yh, yl = gmul(yh ~ bh, yl ~ bl, hh, hl)
    end
  end
  absorb(aad)
  absorb(ct)
  yh, yl = gmul(yh ~ (#aad * 8), yl ~ (#ct * 8), hh, hl)
  return string.pack(">i8i8", yh, yl)
end

local function xor_str(a, b)
  local out = {}
  for i = 1, #a do out[i] = a:byte(i) ~ b:byte(i) end
  return string.char(table.unpack(out))
end
M.xor = xor_str

-- 카운터 2부터 시작하는 CTR 키스트림으로 data를 암·복호화한다 (카운터 1은 태그용 J0).
local function ctr(w, iv, data)
  local out = {}
  local counter = 2
  for i = 1, #data, 16 do
    local chunk = data:sub(i, i + 15)
    local ks = aes.encrypt_block(w, iv .. string.pack(">I4", counter))
    out[#out + 1] = xor_str(chunk, ks)
    counter = counter + 1
  end
  return table.concat(out)
end

local function tag_for(w, iv, aad, ct)
  local hh, hl = string.unpack(">i8i8", aes.encrypt_block(w, string.rep("\0", 16)))
  local s = ghash(hh, hl, aad, ct)
  return xor_str(s, aes.encrypt_block(w, iv .. "\0\0\0\1"))
end

--- 암호화. ciphertext, tag(16바이트)를 돌려준다.
function M.encrypt(key, iv, plaintext, aad)
  assert(#iv == 12, "GCM IV must be 12 bytes")
  local w = aes.expand_key(key)
  local ct = ctr(w, iv, plaintext)
  return ct, tag_for(w, iv, aad or "", ct)
end

--- 복호화. 태그가 맞으면 plaintext, 아니면 nil, "auth"를 돌려준다.
function M.decrypt(key, iv, ciphertext, aad, tag)
  assert(#iv == 12, "GCM IV must be 12 bytes")
  local w = aes.expand_key(key)
  if tag_for(w, iv, aad or "", ciphertext) ~= tag then
    return nil, "auth"
  end
  return ctr(w, iv, ciphertext)
end

return M
