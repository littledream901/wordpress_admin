import { request } from '@/utils'

export default {
  // 站点 CRUD
  getSiteList: (params = {}) => request.get('/site-pipeline/site/list', { params }),
  getSiteById: (params = {}) => request.get('/site-pipeline/site/get', { params }),
  createSite: (data = {}) => request.post('/site-pipeline/site/create', data),
  updateSite: (data = {}) => request.post('/site-pipeline/site/update', data),
  deleteSite: (params = {}) => request.post('/site-pipeline/site/delete', null, { params }),

  // 站点批量操作
  batchCreateSites: (data = {}) => request.post('/site-pipeline/site/batch-create', data),
  batchDeleteSites: (ids = []) => request.post('/site-pipeline/site/batch-delete', ids),
  batchDns: (ids = []) => request.post('/site-pipeline/site/batch-dns', ids),
  batchProvision: (ids = []) => request.post('/site-pipeline/site/batch-provision', ids),
  batchDynadotNs: (ids = [], nsList = '') => request.post('/site-pipeline/site/batch-dynadot-ns', { site_ids: ids, ns_list: nsList }),
  batchRedirect: (ids = [], targetUrl = '') => request.post('/site-pipeline/site/batch-redirect', { site_ids: ids, target_url: targetUrl }),
  batchHubDispatch: (ids = [], jobType = 'create_env') => request.post('/site-pipeline/site/batch-hub-dispatch', { site_ids: ids, job_type: jobType }),
  batchWooImport: (ids = []) => request.post('/site-pipeline/site/batch-woo-import', ids),
  batchAssign: (data = {}) => request.post('/site-pipeline/site/batch-assign', data),

  // 单条操作
  provisionSite: (siteId) => request.post(`/site-pipeline/site/${siteId}/provision`),
  provisionDns: (siteId) => request.post(`/site-pipeline/site/${siteId}/dns`),
  provisionDynadotNs: (siteId) => request.post(`/site-pipeline/site/${siteId}/dynadot-ns`),
  provisionRedirect: (siteId, data = { target_url: '' }) => request.post(`/site-pipeline/site/${siteId}/redirect`, data),
  importWoo: (siteId) => request.post(`/site-pipeline/site/${siteId}/woo-import`),
  refreshWooCount: (siteId) => request.post(`/site-pipeline/site/${siteId}/refresh-woo-count`),

  // HubStudio
  getHubJobList: (params = {}) => request.get('/site-pipeline/hub-job/list', { params }),
  createHubJob: (data = {}) => request.post('/site-pipeline/hub-job/create', data),
  dispatchHubJob: (siteId, data = { job_type: 'create_env' }) => request.post(`/site-pipeline/hub-job/sites/${siteId}/dispatch`, data),
  retryHubJob: (jobId) =>
    request.post(`/site-pipeline/hub-job/${jobId}/retry`, {}),
  cancelHubJob: (jobId) =>
    request.post(`/site-pipeline/hub-job/${jobId}/cancel`, {}),
  batchCancelHubJobs: (jobIds) =>
    request.post('/site-pipeline/hub-job/batch-cancel', { job_ids: jobIds }),

  // Agent 状态
  getAgentStatus: () => request.get('/site-pipeline/hub-job/agents'),

  // HubStudio Site 快捷入口
  triggerHubEnv: (siteId, providerId = 0, executeNow = false) => request.post(`/site-pipeline/site/${siteId}/hub-env`, { provider_id: providerId, execute_now: executeNow }),
  triggerHubAccount: (siteId, providerId = 0, executeNow = false) => request.post(`/site-pipeline/site/${siteId}/hub-account`, { provider_id: providerId, execute_now: executeNow }),
  triggerHubUpdate: (siteId, providerId = 0, executeNow = false) => request.post(`/site-pipeline/site/${siteId}/hub-update`, { provider_id: providerId, execute_now: executeNow }),
  triggerHubControl: (siteId, providerId = 0, executeNow = false) => request.post(`/site-pipeline/site/${siteId}/hub-control`, { provider_id: providerId, execute_now: executeNow }),
  triggerHubGmcCheck: (siteId, providerId = 0, executeNow = false) => request.post(`/site-pipeline/site/${siteId}/hub-gmc-check`, { provider_id: providerId, execute_now: executeNow }),

  // 操作任务查询
  getJob: (params = {}) => request.get('/operation-jobs/get', { params }),

  // Feed 文件管理
  getFeedSourceList: (params = {}) => request.get('/site-pipeline/feed/source-list', { params }),
  getFeedProcessedList: (params = {}) => request.get('/site-pipeline/feed/processed-list', { params }),
  uploadFeed: (formData) => request.post('/site-pipeline/feed/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  createFeed: (id, targetDomain, sourceDomain = '') => request.post(`/site-pipeline/feed/${id}/create-feed`, { target_domain: targetDomain, source_domain: sourceDomain }),
  deleteFeed: (id) => request.delete(`/site-pipeline/feed/${id}`),
  getFeedDefaultDomain: () => request.get('/site-pipeline/feed/config/default-domain'),
  getFeedDownloadUrl: (filename) => `/site-pipeline/feed/download/${encodeURIComponent(filename)}`,
}
