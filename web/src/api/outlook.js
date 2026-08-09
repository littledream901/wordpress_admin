import { request } from '@/utils'

export default {
  getList: (params = {}) => request.get('/outlook/list', { params }),
  create: (data = {}) => request.post('/outlook/create', data),
  update: (data = {}) => request.post('/outlook/update', data),
  assign: (data = {}) => request.post('/outlook/assign', data),
  autoAssign: (siteId) => request.post('/outlook/auto-assign', { site_id: siteId }),
  batchAutoAssign: (siteIds) => request.post('/outlook/batch-auto-assign', { site_ids: siteIds }),
  unassign: (siteId) => request.post('/outlook/unassign', { site_id: siteId }),
  batchCreate: (items = []) => request.post('/outlook/batch-create', items),
  batchAssign: (data = {}) => request.post('/outlook/batch-assign', data),
  batchDelete: (ids = []) => request.post('/outlook/batch-delete', ids),
  setHealthStatus: (data = {}) => request.post('/outlook/set-health', data),
}
