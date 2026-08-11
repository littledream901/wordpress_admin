import { request } from '@/utils'

/** HubStudio 代理池管理 */
export default {
  // 列表
  getList: (params = {}) => request.get('/hubstudio-proxy/list', { params }),
  // 详情
  getDetail: (proxyId) => request.get('/hubstudio-proxy/get', { params: { proxy_id: proxyId } }),
  // 新增
  create: (data) => request.post('/hubstudio-proxy/create', data),
  // 批量导入：host:port:account:password
  batchImport: (data) => request.post('/hubstudio-proxy/batch-import', data),
  // 更新
  update: (data) => request.post('/hubstudio-proxy/update', data),
  // 删除（软删除）
  delete: (proxyId) => request.delete('/hubstudio-proxy/delete', { params: { proxy_id: proxyId } }),
  // 批量删除（软删除）
  batchDelete: (proxyIds) => request.post('/hubstudio-proxy/batch-delete', { proxy_ids: proxyIds }),
  // 批量检测
  batchCheck: (proxyIds) => request.post('/hubstudio-proxy/batch-check', { proxy_ids: proxyIds }),
  // 单条检测
  checkProxy: (proxyId) => request.post('/hubstudio-proxy/check', null, { params: { proxy_id: proxyId } }),
  // 获取分配的站点列表
  getAssignedSites: (proxyId) => request.get('/hubstudio-proxy/assigned-sites', { params: { proxy_id: proxyId } }),
  // 下拉选项
  getOptions: () => request.get('/hubstudio-proxy/options'),
  // 站点批量分配代理
  batchAssignSites: (data) => request.post('/hubstudio-proxy/batch-assign-sites', data),
  // 批量取消代理分配
  batchUnassign: (proxyIds) => request.post('/hubstudio-proxy/batch-unassign', { proxy_ids: proxyIds }),
}

