-- Atomic sliding-window admission.
-- KEYS[1]  Redis sorted set key
-- ARGV[1]  now (unix seconds, may be fractional)
-- ARGV[2]  window seconds
-- ARGV[3]  max admits in the window
-- ARGV[4]  unique member (job id + attempt)
--
-- Returns: { admitted (0|1), current_count }

local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local cutoff = now - window

redis.call("ZREMRANGEBYSCORE", key, "-inf", cutoff)
local current = tonumber(redis.call("ZCARD", key))

if current >= limit then
  return {0, current}
end

redis.call("ZADD", key, now, member)
redis.call("EXPIRE", key, math.ceil(window) + 2)
current = current + 1
return {1, current}
