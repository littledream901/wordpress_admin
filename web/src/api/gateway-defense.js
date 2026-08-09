/**
 * 网关防御 API
 */
import request from './index'

/**
 * 部署网关防御
 * @param {number} siteId - 站点ID
 * @param {object} data - 部署配置
 * @param {string} data.gateway_url - 网关地址
 * @param {string} data.gateway_site_id - 网关站点ID（由网关侧分配，必填）
 * @param {string} data.site_key - 站点密钥（必填）
 * @param {string} data.site_secret - 站点签名密钥（必填）
 * @param {string} [data.fail_mode='open'] - 失败模式: open / closed
 * @param {boolean} [data.sdk_inject=true] - 是否注入 SDK
 */
export function deployGatewayDefense(siteId, data) {
  return request.post(`/site-pipeline/site/${siteId}/gateway-defense`, data)
}

/**
 * 批量部署网关防御
 * @param {object} data - 批量部署配置
 * @param {number[]} data.site_ids - 站点ID列表
 * @param {string} data.gateway_url - 网关地址
 * @param {object} data.credentials_map - 站点ID → {gateway_site_id, site_key, site_secret} 映射（必填）
 * @param {string} [data.fail_mode='open'] - 失败模式
 * @param {boolean} [data.sdk_inject=true] - 是否注入 SDK
 */
export function batchDeployGatewayDefense(data) {
  return request.post('/site-pipeline/site/batch-gateway-defense', data)
}

/**
 * 获取站点网关凭证
 * @param {number} siteId - 站点ID
 */
export function getGatewayCredentials(siteId) {
  return request.get(`/site-pipeline/site/${siteId}/gateway-credentials`)
}

/**
 * 获取站点网关防御 Provider 信息
 * @param {number} siteId - 站点ID
 */
export function getGatewayProviderInfo(siteId) {
  return request.get(`/site-pipeline/site/${siteId}/gateway-provider-info`)
}

/**
 * 更新网关防御配置
 * @param {number} siteId - 站点ID
 * @param {object} data - 更新配置
 */
export function updateGatewayDefense(siteId, data) {
  return request.post(`/site-pipeline/site/${siteId}/gateway-defense/update`, data)
}
