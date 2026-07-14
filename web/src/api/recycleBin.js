import { request } from '@/utils'

export default {
  getList(params) { return request.get('/recycle-bin/list', { params }) },
  restore(data) { return request.post('/recycle-bin/restore', data) },
  permanentDelete(data) { return request.post('/recycle-bin/permanent-delete', data) },
  empty(data) { return request.post('/recycle-bin/empty', data) },
}
