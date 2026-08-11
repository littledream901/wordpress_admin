-- 修复缺失的 gateway 相关字段
-- 执行方式: mysql -h <host> -u admin -p vue_fastapi_admin < fix_gateway_fields.sql

ALTER TABLE site_pipeline_site 
  ADD COLUMN gateway_defense_status VARCHAR(64) NOT NULL DEFAULT '' COMMENT '网关防御状态' AFTER shopify_token,
  ADD COLUMN gateway_defense_type VARCHAR(32) NOT NULL DEFAULT '' COMMENT '网关防御类型: worker / nginx_lua' AFTER gateway_defense_status,
  ADD COLUMN gateway_site_key VARCHAR(255) NOT NULL DEFAULT '' COMMENT '网关站点密钥 (site_xxxxxxxx)' AFTER gateway_defense_type,
  ADD COLUMN gateway_site_secret VARCHAR(255) NOT NULL DEFAULT '' COMMENT '网关签名密钥' AFTER gateway_site_key,
  ADD COLUMN gateway_deployed_at DATETIME(6) NULL COMMENT '网关部署时间' AFTER gateway_site_secret,
  ADD COLUMN gateway_config_json TEXT COMMENT '网关配置(JSON)' AFTER gateway_deployed_at,
  ADD COLUMN gateway_last_error TEXT COMMENT '最后错误信息' AFTER gateway_config_json,
  ADD INDEX idx_gateway_defense_status (gateway_defense_status);
