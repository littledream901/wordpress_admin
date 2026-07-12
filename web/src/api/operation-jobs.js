import { request } from '@/utils'

export default {
  getList: (params = {}) => request.get('/operation-jobs/list', { params }),
  getById: (params = {}) => request.get('/operation-jobs/get', { params }),
  batchCreate: (data) => request.post('/operation-jobs/batch-create', data),
  update: (data) => request.post('/operation-jobs/update', data),
  cancel: (id) => request.post('/operation-jobs/cancel', { id }),
}
