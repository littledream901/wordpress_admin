server {
    listen 80 ; 
    listen 443 ssl ; 
    server_name qciqcgsi.shop; 


    include /www/sites/qciqcgsi-shop-038745-1786472355632/lua/fangyu_real_ip.conf;

    # Fangyu Defense 配置
    set $fangyu_gateway_url  "https://gateway.foxfingerlab.com";
    set $fangyu_site_id      "3";
    set $fangyu_site_key     "site_a8d1e78e";
    set $fangyu_site_secret  "aefb5b8d165d0ad3e093e3953931235bb84e80ac0fa86904";
    set $fangyu_fail_mode    "open";
    set $fangyu_sdk_inject   "on";
    set $fangyu_blocked_url  "/blocked";
    set $fangyu_challenge_url "/challenge";
    set $fy_sdk_snippet      "";
    set $fy_server_token     "";

    index index.php index.html index.htm default.php default.htm default.html; 
    access_log /www/sites/qciqcgsi-shop-038745-1786472355632/log/access.log main; 
    error_log /www/sites/qciqcgsi-shop-038745-1786472355632/log/error.log; 
    location ~ ^/(\.user.ini|\.htaccess|\.git|\.env|\.svn|\.project|LICENSE|README.md) {
        return 404; 
    }
    location ^~ /.well-known/acme-challenge {
        allow all; 
        root /usr/share/nginx/html; 
    }
    if ( $uri ~ "^/\.well-known/.*\.(php|jsp|py|js|css|lua|ts|go|zip|tar\.gz|rar|7z|sql|bak)$" ) {
        return 403; 
    }
    location / {
        access_by_lua_file /www/sites/qciqcgsi-shop-038745-1786472355632/lua/defense.lua;
        proxy_set_header Accept-Encoding "";
        proxy_hide_header Content-Encoding;
        proxy_set_header Host $host; 
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; 
        proxy_set_header X-Forwarded-Host $server_name; 
        proxy_set_header X-Real-IP $remote_addr; 
        proxy_set_header X-Forwarded-Proto $scheme; 
        proxy_set_header Connection upgrade; 
        proxy_set_header Upgrade $http_upgrade; 
        proxy_http_version 1.1; 
        proxy_ssl_server_name off; 
        proxy_ssl_name $proxy_host; 
        proxy_pass http://127.0.0.1:26439; 
        body_filter_by_lua_block {
            local snippet = ngx.var.fy_sdk_snippet
            if not snippet or snippet == "" then return end

            local content_type = ngx.header["Content-Type"] or ""
            if type(content_type) == "string" and string.find(content_type, "text/html", 1, true) then
                local chunk = ngx.arg[1]
                if chunk and type(chunk) == "string" and chunk ~= "" then
                    local safe_snippet = snippet:gsub("%%", "%%%%")
                    local new_chunk, count = string.gsub(chunk, "</head>", safe_snippet .. "</head>", 1)
                    if count > 0 then
                        ngx.arg[1] = new_chunk
                    end
                end
            end
        }
    }
    http2 on; 
    if ($scheme = http) {
        return 301 https://$host$request_uri; 
    }
    ssl_certificate /www/sites/qciqcgsi-shop-038745-1786472355632/ssl/fullchain.pem; 
    ssl_certificate_key /www/sites/qciqcgsi-shop-038745-1786472355632/ssl/privkey.pem; 
    ssl_protocols TLSv1.3 TLSv1.2; 
    ssl_ciphers ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-SHA384:ECDHE-RSA-AES128-SHA256:!aNULL:!eNULL:!EXPORT:!DSS:!DES:!RC4:!3DES:!MD5:!PSK:!KRB5:!SRP:!CAMELLIA:!SEED; 
    ssl_prefer_server_ciphers off; 
    ssl_session_cache shared:SSL:10m; 
    ssl_session_timeout 10m; 
    error_page 497 https://$host$request_uri; 
    proxy_set_header X-Forwarded-Proto https; 
}