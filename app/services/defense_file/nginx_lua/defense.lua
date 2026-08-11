-- [DEBUG] defense.lua 开始执行
ngx.log(ngx.ERR, "[fangyu-test] ========== defense.lua loaded ==========")

--[[
  Fangyu Defense — Nginx / OpenResty adapter
  ============================================
  Drop this file into your OpenResty config and wire it via access_by_lua_file:

    location / {
        access_by_lua_file /path/to/defense.lua;
        proxy_pass http://upstream;
    }

  Dependencies (available in any OpenResty bundle ≥ 1.21):
    lua-resty-http    — ngx.location.capture alternative for subrequests
    lua-resty-hmac    — or use resty.openssl.hmac (OpenResty 1.25+)
    lua-cjson         — bundled with OpenResty

  ⚠️ 部署清单（Deployment Checklist）⚠️
  ======================================
  请按顺序完成以下配置，缺一不可：

  ✓ 1. 在 nginx.conf 的 server 块中配置以下变量：

    set $fangyu_gateway_url  "https://defense.example.com";
    set $fangyu_site_key     "site_xxxxxxxx";   -- 站点密钥字符串，用作 X-App-Key 请求头
    set $fangyu_site_id      "1";               -- 站点数字主键（Site.id），用于 SDK 配置的 siteId 参数
    set $fangyu_site_secret  "your_site_secret"; -- 站点签名密钥
    set $fangyu_fail_mode    "open";            -- "open" or "closed"
    set $fangyu_sdk_inject   "on";              -- "on"(默认) 或 "off"
    set $fangyu_sdk_url      "";                -- SDK URL，空=自动用 gateway_url/sdk/fangyu-sdk.min.js
    set $fangyu_blocked_url  "/blocked";
    set $fangyu_challenge_url "/challenge";
    set $fy_sdk_snippet      "";                -- ⚠️ 关键！SDK 注入必需！

  ✓ 2. 在 location / 块中添加：
    access_by_lua_file /www/sites/{your-domain}/lua/defense.lua;

  ✓ 3. 在 location / 块或 server 块末尾添加 body_filter：
    body_filter_by_lua_block {
        local snippet = ngx.var.fy_sdk_snippet
        if not snippet or snippet == "" then return end
        local ct = ngx.header["Content-Type"] or ""
        if not ct:find("text/html", 1, true) then return end
        local chunk, eof = ngx.arg[1], ngx.arg[2]
        if chunk then
            local before = chunk
            ngx.arg[1] = chunk:gsub("</head>", snippet .. "</head>", 1)
            -- 验证注入是否成功
            if ngx.arg[1] ~= before then
                ngx.log(ngx.INFO, "[fangyu] SDK 注入成功 (找到 </head> 标签)")
            end
        end
    }

  ✓ 4. 验证配置：
    nginx -t && nginx -s reload

  ✓ 5. 测试 SDK 注入：
    curl -I https://your-domain.com/
    # 查看页面源代码，搜索 "fangyu-sdk" 或 "__fy_server_ctx"

  故障排查：
    运行诊断工具: python diagnose_sdk_injection.py
    查看文档: docs/SDK_INJECTION_TROUBLESHOOTING.md

  Signing parity
  --------------
  The build_payload() function below must produce byte-identical output to:
    Python  fangyu_shared.security.signing.build_sign_payload
    TS      client-sdk/src/core/signer.ts :: buildSignPayload
    PHP     class-fangyu-signer.php       :: build_payload
  All four are validated by client-sdk/tests/fixtures/sign_vectors.json.

  Verified encoding edge cases (matching encodeURIComponent, NOT rawurlencode):
    !  →  !      (RFC3986 would give %21)
    *  →  *      (RFC3986 would give %2A)
    '  →  '      (RFC3986 would give %27)
    (  →  (      (RFC3986 would give %28)
    )  →  )      (RFC3986 would give %29)
    /  →  %2F
       →  %20   (not +)
--]]

local cjson  = require "cjson.safe"
local resty_hmac = nil
-- OpenResty 1.25+ ships resty.openssl.hmac; older builds use lua-resty-hmac.
-- We attempt both; fail loudly if neither is available rather than silently
-- computing wrong signatures.
local ok, mod = pcall(require, "resty.openssl.hmac")
if ok then
  resty_hmac = mod
else
  ok, mod = pcall(require, "resty.hmac")
  if ok then resty_hmac = mod end
end
if not resty_hmac then
  ngx.log(ngx.CRIT, "[fangyu] neither resty.openssl.hmac nor resty.hmac found")
  -- fail-open: let the request through rather than crash the server
  return
end

local http = require "resty.http"

-- ── Config ──────────────────────────────────────────────────────────────────

local function cfg(key, default)
  local v = ngx.var["fangyu_" .. key]
  if v == nil or v == "" then return default end
  return v
end

local GATEWAY_URL  = cfg("gateway_url", "")
local SITE_KEY     = cfg("site_key", "")
-- 浏览器 SDK 需要数值型 appId（SdkConfig.appId 校验 `Number.isInteger && > 0`）。
-- 注意：此处的 SITE_ID 是站点数字主键（Site.id），用于 SDK 配置的 appId 参数。
-- SITE_KEY 是字符串键（site_xxxxxxxx），用作 X-App-Key 请求头。
local SITE_ID      = tonumber(cfg("site_id", "0")) or 0
local SITE_SECRET  = cfg("site_secret", "")
local FAIL_MODE    = cfg("fail_mode", "open")
local SDK_INJECT   = cfg("sdk_inject", "on")
local SDK_URL      = cfg("sdk_url", "")
local BLOCKED_URL  = cfg("blocked_url", "/blocked")
local CHALLENGE_URL = cfg("challenge_url", "/challenge")

-- ── Environment Self-Check ──────────────────────────────────────────────────

local function check_environment()
  local errors = {}
  
  -- 检查必需的 Nginx 变量是否可访问
  local ok, err = pcall(function()
    local test = ngx.var.fy_sdk_snippet
  end)
  
  if not ok then
    table.insert(errors, "$fy_sdk_snippet 变量未声明")
    ngx.log(ngx.CRIT, "[fangyu] CRITICAL: $fy_sdk_snippet 变量未声明！")
    ngx.log(ngx.CRIT, "[fangyu] 修复方法: 在 nginx.conf 中添加: set $fy_sdk_snippet \"\";")
  end
  
  -- 检查关键配置是否缺失
  if GATEWAY_URL == "" then
    table.insert(errors, "$fangyu_gateway_url 未配置")
    ngx.log(ngx.ERR, "[fangyu] ERROR: $fangyu_gateway_url 未配置")
  end
  
  if SITE_KEY == "" then
    table.insert(errors, "$fangyu_site_key 未配置")
    ngx.log(ngx.ERR, "[fangyu] ERROR: $fangyu_site_key 未配置（用作 X-App-Key）")
  end
  
  if SITE_ID == 0 then
    table.insert(errors, "$fangyu_site_id 未配置或无效（需要 > 0 的整数）")
    ngx.log(ngx.ERR, "[fangyu] ERROR: $fangyu_site_id 未配置或无效（用于 SDK siteId）")
  end
  
  if SITE_SECRET == "" then
    table.insert(errors, "$fangyu_site_secret 未配置")
    ngx.log(ngx.ERR, "[fangyu] ERROR: $fangyu_site_secret 未配置")
  end
  
  if #errors > 0 then
    ngx.log(ngx.CRIT, "[fangyu] 环境检查失败，发现 " .. #errors .. " 个问题:")
    for _, e in ipairs(errors) do
      ngx.log(ngx.CRIT, "[fangyu]   - " .. e)
    end
    return false, errors
  end
  
  return true, nil
end

-- 执行环境检查
local env_ok, env_errors = check_environment()
if not env_ok then
  if FAIL_MODE == "closed" then
    ngx.log(ngx.CRIT, "[fangyu] fail_mode=closed，拒绝请求")
    ngx.exit(503)  -- Service Unavailable
  else
    ngx.log(ngx.WARN, "[fangyu] fail_mode=open，放行请求但功能受限")
    return  -- 放行但不执行防御逻辑
  end
end

-- ── Signing ──────────────────────────────────────────────────────────────────

-- Characters NOT encoded by encodeURIComponent (beyond A-Za-z0-9):
local SAFE_CHARS = {
  ["-"] = true, ["_"] = true, ["."] = true, ["!"] = true,
  ["~"] = true, ["*"] = true, ["'"] = true, ["("] = true, [")"] = true,
}

local function encode_component(s)
  s = tostring(s)
  return (s:gsub("[^A-Za-z0-9%-_.!~*'()]", function(c)
    return string.format("%%%02X", string.byte(c))
  end))
end

-- Deep-sort an object's keys (lists are preserved in order).
-- Returns a new table ready for cjson.encode.
local function sort_deep(val)
  local t = type(val)
  if t == "table" then
    -- Detect list vs object: a list has only integer keys 1..n.
    local is_list = true
    local n = #val
    for k, _ in pairs(val) do
      if type(k) ~= "number" or k < 1 or k > n or k ~= math.floor(k) then
        is_list = false
        break
      end
    end
    if is_list then
      local out = {}
      for i, v in ipairs(val) do out[i] = sort_deep(v) end
      return out
    else
      -- Object: collect & sort keys
      local keys = {}
      for k in pairs(val) do keys[#keys+1] = tostring(k) end
      table.sort(keys)
      -- cjson needs a special marker to emit {} not []; use cjson.empty_array trick
      -- workaround: rebuild as a plain table with sorted keys stored in metatable order
      -- Actually cjson.encode on a table with mixed / non-sequential keys emits object.
      local out = {}
      for _, k in ipairs(keys) do
        if val[k] ~= nil then
          out[k] = sort_deep(val[k])
        end
      end
      return out
    end
  end
  return val
end

local function canonical_json(val)
  local sorted = sort_deep(val)
  return cjson.encode(sorted)
end

local function stringify_value(val)
  local t = type(val)
  if t == "boolean" then
    return val and "true" or "false"
  elseif t == "table" then
    return canonical_json(val)
  else
    return tostring(val)
  end
end

local EXCLUDED_KEYS = { sign = true }

local function build_payload(params)
  -- collect and sort keys
  local keys = {}
  for k in pairs(params) do keys[#keys+1] = tostring(k) end
  table.sort(keys)

  local parts = {}
  for _, k in ipairs(keys) do
    if not EXCLUDED_KEYS[k] then
      local v = params[k]
      if v ~= nil and v ~= "" then
        -- false (boolean) must be kept; only nil and "" are dropped.
        parts[#parts+1] = encode_component(k) .. "=" .. encode_component(stringify_value(v))
      end
    end
  end
  return table.concat(parts, "&")
end

local function compute_hmac(secret, message)
  -- resty.openssl.hmac API
  if resty_hmac.new then
    local h, err = resty_hmac.new(secret, "sha256")
    if not h then
      ngx.log(ngx.ERR, "[fangyu] hmac init error: ", err)
      return nil
    end
    h:update(message)
    local digest = h:final()
    -- convert binary to hex
    return (digest:gsub(".", function(c)
      return string.format("%02x", string.byte(c))
    end))
  end
  -- lua-resty-hmac API (older)
  local h = resty_hmac:new(secret, resty_hmac.ALGOS.SHA256)
  if not h then return nil end
  h:update(message)
  return h:final(nil, true) -- hex
end

local function nonce()
  -- 16 random bytes → 32 hex chars
  local bytes = {}
  for i = 1, 16 do bytes[i] = string.format("%02x", math.random(0, 255)) end
  return table.concat(bytes)
end

local function sign_body(body, secret)
  body.timestamp = ngx.time()
  body.nonce     = nonce()
  body.sign      = compute_hmac(secret, build_payload(body))
  return body
end

-- ── Gateway call ─────────────────────────────────────────────────────────────

local function decide(context)
  if GATEWAY_URL == "" or SITE_KEY == "" or SITE_SECRET == "" then
    return nil, "not_configured"
  end

  local body_tbl = {
    context        = context,
    requireDetails = false,
  }
  sign_body(body_tbl, SITE_SECRET)

  local body_str, encode_err = cjson.encode(body_tbl)
  if not body_str then
    return nil, "json_encode: " .. (encode_err or "?")
  end

  local httpc = http.new()
  httpc:set_timeout(3000) -- 3 s

  local res, err = httpc:request_uri(GATEWAY_URL .. "/v2/decide", {
    method  = "POST",
    headers = {
      ["Content-Type"] = "application/json; charset=utf-8",
      ["X-App-Key"]    = SITE_KEY,  -- 使用站点密钥字符串
    },
    body = body_str,
    ssl_verify = false,
  })

  if not res or res.status < 200 or res.status >= 300 then
    local err_msg = err or ("http " .. (res and res.status or "?"))
    if res and res.body then
      local body_preview = string.sub(res.body, 1, 512)
      ngx.log(ngx.ERR, "[fangyu] decide failed: ", err_msg, ", response body (first 512 bytes): ", body_preview)
    else
      ngx.log(ngx.ERR, "[fangyu] decide failed: ", err_msg)
    end
    return nil, err_msg
  end

  local data, derr = cjson.decode(res.body)
  if not data then return nil, "json_decode: " .. (derr or "?") end

  -- Support wrapped { data: {...} } and bare {...} shapes.
  local payload = (data.data and type(data.data) == "table") and data.data or data
  return payload, nil
end

-- ── Disposition execution ─────────────────────────────────────────────────────

-- 向网关上报心跳（异步，失败不影响主流程）
local function send_heartbeat(fingerprint)
  if not fingerprint or fingerprint == "" then return end
  
  local now_ms = ngx.now() * 1000
  local body = {
    siteId = SITE_ID,
    fingerprint = fingerprint,
    sdkVersion = "nginx-adapter-2.0",
    behaviorEvents = {
      { kind = "page_view", ts = math.floor(now_ms), value = 1 }
    }
  }
  
  local signed_body = sign_body(body, SITE_SECRET)
  local httpc = http.new()
  httpc:set_timeout(3000)
  
  local res, err = httpc:request_uri(GATEWAY_URL .. "/v2/sdk/heartbeat", {
    method = "POST",
    headers = {
      ["Content-Type"] = "application/json",
      ["X-App-Key"] = SITE_KEY,
    },
    body = cjson.encode(signed_body),
  })
  
  if not res then
    ngx.log(ngx.WARN, "[fangyu] heartbeat failed: ", err)
  elseif res.status < 200 or res.status >= 300 then
    -- 记录响应体前 512 字节，便于定位签名/字段错误
    local body_preview = string.sub(res.body or "", 1, 512)
    ngx.log(ngx.WARN, "[fangyu] heartbeat rejected: HTTP ", res.status, ", body=", body_preview)
  end
  
  httpc:close()
end

local function execute(payload)
  if not payload then return end
  local mech = payload.mechanism or "pass"

  if mech == "pass" then
    return  -- allow
  elseif mech == "redirect" then
    local url = payload.targetUrl
    ngx.log(ngx.ERR, "[fangyu-debug] redirect targetUrl: ", url or "nil")
    if url and (url:sub(1,7) == "http://" or url:sub(1,8) == "https://") then
      local status = tonumber(payload.httpStatus) or 302
      if status < 300 or status >= 400 then status = 302 end
      ngx.log(ngx.ERR, "[fangyu-debug] Calling ngx.redirect(", url, ", ", status, ")")
      return ngx.redirect(url, status)
    end
    -- No valid URL → fall through to deny
    ngx.log(ngx.ERR, "[fangyu-debug] No valid URL, returning 403")
    ngx.exit(403)
  elseif mech == "not_found" then
    local status = tonumber(payload.httpStatus) or 404
    if payload.targetKind == "status_only" then
      ngx.status = status
      return ngx.exit(ngx.HTTP_OK)
    end
    ngx.exit(status)
  elseif mech == "deny" then
    local status = tonumber(payload.httpStatus) or 403
    if payload.targetKind == "status_only" then
      ngx.status = status
      return ngx.exit(ngx.HTTP_OK)
    end
    ngx.exit(status)
  elseif mech == "serve_alt" or mech == "challenge" then
    local content = payload.pageContent
    if content and content ~= "" then
      ngx.header["Content-Type"] = "text/html; charset=utf-8"
      ngx.status = 200
      ngx.say(content)
      return ngx.exit(ngx.HTTP_OK)
    end
    ngx.exit(403)
  else
    -- 未知机制：记 WARN 日志，按 fail_mode 决策
    ngx.log(ngx.WARN, "[fangyu] unknown mechanism: ", mech, ", fail_mode=", FAIL_MODE)
    if FAIL_MODE == "closed" then
      ngx.exit(403)
    end
    -- fail_mode=open 时放行（兜底行为）
  end
end

-- ── SDK 注入 ─────────────────────────────────────────────────────────────────

-- 生成服务端 session token（16字节随机十六进制）
local function server_session_token()
  local bytes = {}
  math.randomseed(ngx.now() * 1000 + ngx.worker.pid())
  for i = 1, 16 do bytes[i] = string.format("%02x", math.random(0, 255)) end
  return "sst_" .. table.concat(bytes)
end

-- 向 HTML 响应体注入 SDK snippet（仅当 Content-Type 含 text/html 时调用）
local function build_sdk_snippet(server_verdict, server_token)
  local sdk_src = SDK_URL ~= "" and SDK_URL
    or (GATEWAY_URL .. "/sdk/fangyu-sdk.min.js")

  -- 键名必须与 SdkConfig 对齐：apiBase / apiKey / siteId。
  -- 注意：apiKey 是站点密钥字符串（SITE_KEY），siteId 是站点数字主键（SITE_ID）
  local ctx_json = cjson.encode({
    apiBase       = GATEWAY_URL,
    apiKey        = SITE_KEY,      -- 站点密钥字符串（site_xxxxxxxx）
    siteId        = SITE_ID,       -- 站点数字主键（Site.id）
    serverVerdict = server_verdict or "unknown",
    serverToken   = server_token,
    blockedUrl    = BLOCKED_URL,
    challengeUrl  = CHALLENGE_URL,
  })

  -- SDK 刻意保持 defer + DOMContentLoaded，**不要**改成同步阻塞。
  --
  -- 本段只在服务端判 pass 时才注入（见文件末尾主流程：mechanism ~= "pass" 时
  -- 直接 execute 并 return，不注入）。能看到这段脚本的访客都已通过第一层，
  -- 客户端层的跳转命中率按设计就低；且 HTML 此刻已完整下发给浏览器，
  -- 同步阻塞连「防正文泄露」都做不到。为少数残余命中让所有已放行的真人
  -- 多等一次阻塞解析，不划算。
  --
  -- 需要「HTML 都不下发」的拦截强度，靠的是第一层的边缘判定，不是这里。
  --
  -- 例外：不带服务端层的纯 SDK 接入（后台生成的接入片段）应当用同步 +
  -- SdSdk.guard()，因为那里 SDK 是唯一防线，跳转命中率也高得多。
  return string.format([[
<script>
window.__fy_server_ctx = %s;
</script>
<script src="%s" defer></script>
<script>
(function () {
  var ctx = window.__fy_server_ctx || {};
  // 这一段同步执行（不依赖 SDK）：缓存命中已知 hostile 时立刻跳，0ms 无网络。
  // 存 {v, exp} 而非裸 verdict 是为了让后台配的 ttlSeconds 在边缘侧真正生效。
  // 下面用 autoApply:false，SDK 自身的决策缓存不会自动生效，这一层必须保留。
  var _c = null;
  try { _c = JSON.parse(sessionStorage.getItem('_fy_v') || 'null'); } catch (e) {}
  if (_c && _c.exp > Date.now() && _c.v === 'hostile') {
    if (window.stop) { try { window.stop(); } catch (e) {} }
    location.replace(ctx.blockedUrl || '/blocked'); return;
  }
  document.addEventListener('DOMContentLoaded', function () {
    if (typeof SdSdk === 'undefined') return;
    if (!ctx.apiBase || !ctx.apiKey || !ctx.siteId) return;
    // protect() 返回 Promise<{decision, applied}>；SDK 没有 onDecision 配置项，
    // 处置回调只能从这里取。autoApply:false 时由下面的分支自行执行。
    SdSdk.protect({
      apiBase: ctx.apiBase, apiKey: ctx.apiKey, siteId: ctx.siteId,
      serverToken: ctx.serverToken || '', autoApply: false, collectBehavior: true
    }).then(function (outcome) {
      var d = outcome && outcome.decision;
      if (!d) return;
      try {
        sessionStorage.setItem('_fy_v', JSON.stringify({
          v: d.verdict, exp: Date.now() + (d.ttlSeconds || 300) * 1000
        }));
      } catch (e) {}
      if (d.mechanism === 'redirect') {
        // 跳转前掐掉在途请求，省下已放行页面的剩余子资源流量
        if (window.stop) { try { window.stop(); } catch (e) {} }
        location.replace(d.targetUrl || ctx.blockedUrl);
      } else if (d.mechanism === 'challenge') {
        location.replace(ctx.challengeUrl + '?next=' + encodeURIComponent(location.href));
      } else if (d.mechanism === 'deny') {
        document.documentElement.innerHTML =
          '<body style="font:sans-serif;text-align:center;padding:80px"><h1>403</h1></body>';
      }
    }).catch(function () { /* SDK 异常不影响页面 */ });
  });
}());
</script>
]], ctx_json, sdk_src)
end



-- ── Main ─────────────────────────────────────────────────────────────────────

local function get_client_ip()
  return ngx.var.remote_addr or "0.0.0.0"
end

-- Skip Nginx internal redirects.
if ngx.req.is_internal() then return end

local real_ip = get_client_ip()

local server_token = server_session_token()

local context = {
  siteId    = SITE_ID,  -- 站点数字主键（Site.id），用于 Gateway 租户隔离
  ingress   = "adapter",
  ip        = real_ip,
  visitUrl  = ngx.var.scheme .. "://" .. ngx.var.host .. ngx.var.request_uri,
  -- path / method 必须显式上报：规则引擎的 request.path 直接取该字段，不从
  -- visitUrl 派生。漏报会让「敏感路径阻断」这类规则永不命中，而否定条件
  -- （路径不在白名单则拦截）反而会因取值恒为 "/" 而误拦全站。
  -- uri 不含 query string，正是规则需要的路径部分。
  path      = ngx.var.uri or "/",
  method    = ngx.var.request_method or "GET",
  userAgent = ngx.var.http_user_agent or "",
  referer   = ngx.var.http_referer or "",
  clientLanguage = ngx.var.http_accept_language or "",
  -- serverToken 通过 extra 字段传递，匹配 gateway DecisionContext.extra
  extra     = { serverToken = server_token },
}

local repeat_val = ngx.var.cookie__sd_0000
if repeat_val and repeat_val ~= "" then
  context.fingerprint = repeat_val
  context.repeatKey   = "_sd_0000"
  context.repeatValue = repeat_val
else
  -- 首次访问没有 Cookie，生成匿名指纹以便记录访问日志
  context.fingerprint = "anon_" .. ngx.var.remote_addr .. "_" .. ngx.time()
end

-- DEBUG: 开始决策调用
ngx.log(ngx.ERR, "[fangyu-debug] Starting decision call for: ", context.visitUrl)
ngx.log(ngx.ERR, "[fangyu-debug] Gateway URL: ", GATEWAY_URL)
ngx.log(ngx.ERR, "[fangyu-debug] Site Key: ", SITE_KEY)
ngx.log(ngx.ERR, "[fangyu-debug] Site ID: ", SITE_ID)

local payload, err = decide(context)

-- DEBUG: 决策结果
if err then
  ngx.log(ngx.ERR, "[fangyu-debug] Gateway error: ", err)
  ngx.log(ngx.WARN, "[fangyu] gateway error: ", err)
  if FAIL_MODE == "closed" then ngx.exit(403) end
  -- fail-open：继续执行，SDK 仍然注入
else
  ngx.log(ngx.ERR, "[fangyu-debug] Decision success, mechanism: ", payload and payload.mechanism or "nil")
  if payload then
    ngx.log(ngx.ERR, "[fangyu-debug] Verdict: ", payload.verdict or "unknown")
  end
end

-- 第一层判定为拦截时直接执行（SDK 不加载）
if payload and payload.mechanism ~= "pass" then
  ngx.log(ngx.ERR, "[fangyu-debug] Executing mechanism: ", payload.mechanism)
  ngx.log(ngx.ERR, "[fangyu-debug] Payload: ", require("cjson").encode(payload))
  execute(payload)
  return
end

-- 决策完成后异步上报心跳（使用 ngx.timer.at 避免阻塞主流程）
-- 现在无论是否有 Cookie 都会上报访问日志
if context.fingerprint then
  local ok, err = ngx.timer.at(0, function(premature)
    if not premature then
      send_heartbeat(context.fingerprint)
    end
  end)
  if not ok then
    ngx.log(ngx.WARN, "[fangyu] failed to create heartbeat timer: ", err)
  end
end

local server_token = payload and payload.serverToken or ""

-- 第一层 pass（或网关不可达）→ 注入 SDK 到响应 HTML
-- 使用 header_filter + body_filter 阶段实现；
-- 重要：proxy_pass 会导致 ngx.ctx 在子请求中丢失，但 body_filter 阶段不受影响
if SDK_INJECT ~= "off" then
  local server_verdict = payload and payload.verdict or "unknown"
  local snippet = build_sdk_snippet(server_verdict, server_token)
  
  -- 存入 ngx.ctx 供 body_filter 阶段注入（避免 ngx.var 的 4KB 限制）
  ngx.ctx.fy_sdk_snippet = snippet
  
  ngx.log(ngx.INFO, "[fangyu] SDK snippet 已准备 (", #snippet, " 字节), verdict: ", server_verdict)
  ngx.log(ngx.ERR, "[fangyu-debug] SDK snippet prepared, verdict: ", server_verdict)
else
  ngx.log(ngx.WARN, "[fangyu] SDK 注入已禁用 (SDK_INJECT=off)")
end

--[[
── nginx.conf 配置示例（双层模式）───────────────────────────────────────────

  server {
    # 必需的变量声明
    set $fangyu_gateway_url  "https://gateway.example.com";
    set $fangyu_site_key     "site_xxxxxxxx";      # 站点密钥字符串，用作 X-App-Key 请求头
    set $fangyu_site_id      "1";                  # 站点数字主键（Site.id），用于 SDK 配置的 siteId 参数
    set $fangyu_site_secret  "your_site_secret";   # 站点签名密钥
    set $fangyu_fail_mode    "open";
    set $fangyu_sdk_inject   "on";
    set $fy_sdk_snippet      "";                   # ⚠️ 关键！SDK 注入必需

    location / {
      # 第一层：access 阶段，决策+准备 SDK snippet
      access_by_lua_file /www/sites/your-domain/lua/defense.lua;

      proxy_pass http://upstream;

      # 第二层：body_filter 阶段，把 snippet 注入到 </head> 之前
      body_filter_by_lua_block {
        local snippet = ngx.var.fy_sdk_snippet
        if not snippet or snippet == "" then return end
        
        -- 仅对 HTML 响应注入
        local ct = ngx.header["Content-Type"] or ""
        if not ct:find("text/html", 1, true) then return end
        
        -- 把 snippet 插入到 </head> 之前
        local chunk, eof = ngx.arg[1], ngx.arg[2]
        if chunk then
          local before = chunk
          ngx.arg[1] = chunk:gsub("</head>", snippet .. "</head>", 1)
          
          -- 验证注入是否成功（生产环境可注释此行以减少日志）
          if ngx.arg[1] ~= before then
            ngx.log(ngx.INFO, "[fangyu] SDK 注入成功")
          end
        end
      }
    }
  }

注意：
1. body_filter 方式在流式响应或分块传输时可能只命中第一个 chunk。
   对于大多数业务场景（商品页、活动页）这已经足够。
2. 如需严格保证注入，可在 proxy_pass 前加 proxy_buffering on; 强制缓冲完整响应体。
3. 生产环境建议调整日志级别，避免 INFO 日志过多。
]]
