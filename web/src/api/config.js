import { request } from '@/utils'

export default {
  getCategoryList: () => request.get('/config/category/list'),
  getList: (params = {}) => request.get('/config/list', { params }),
  getById: (params = {}) => request.get('/config/get', { params }),
  create: (data) => request.post('/config/create', data),
  update: (data) => request.post('/config/update', data),
  remove: (id) => request.post('/config/delete', { id }),
  batchSave: (data) => request.post('/config/batch-save', data),
}
