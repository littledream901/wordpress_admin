import { request } from '@/utils'

export default {
  getList: (params = {}) => request.get('/gmail/list', { params }),
  create: (data = {}) => request.post('/gmail/create', data),
  update: (data = {}) => request.post('/gmail/update', data),
  assign: (data = {}) => request.post('/gmail/assign', data),
  autoAssign: (siteId) => request.post('/gmail/auto-assign', { site_id: siteId }),
  batchAutoAssign: (siteIds) => request.post('/gmail/batch-auto-assign', { site_ids: siteIds }),
  unassign: (siteId) => request.post('/gmail/unassign', { site_id: siteId }),
  batchCreate: (items = []) => request.post('/gmail/batch-create', items),
  batchAssign: (data = {}) => request.post('/gmail/batch-assign', data),
  batchDelete: (ids = []) => request.post('/gmail/batch-delete', ids),
  setHealthStatus: (data = {}) => request.post('/gmail/set-health', data),
}
