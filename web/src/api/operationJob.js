import { request } from '@/utils'

export default {
  getList(params) { return request.get('/operation-jobs/list', { params }) },
  getDetail(params) { return request.get('/operation-jobs/get', { params }) },
  batchCreate(data) { return request.post('/operation-jobs/batch-create', data) },
  update(data) { return request.post('/operation-jobs/update', data) },
  cancel(params) { return request.post('/operation-jobs/cancel', null, { params }) },
}
