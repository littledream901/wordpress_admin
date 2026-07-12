import { request } from '@/utils'

export default {
  // Provider
  getProviders(params) { return request.get('/config-provider/provider/list', { params }) },
  getProvider(params) { return request.get('/config-provider/provider/get', { params }) },
  createProvider(data) { return request.post('/config-provider/provider/create', data) },
  updateProvider(data) { return request.post('/config-provider/provider/update', data) },
  deleteProvider(params) { return request.post('/config-provider/provider/delete', null, { params }) },
  setDefaultProvider(params) { return request.post('/config-provider/provider/set-default', null, { params }) },
  getProviderTypes() { return request.get('/config-provider/provider/types') },
  // Items
  getItems(params) { return request.get('/config-provider/items/list', { params }) },
  updateItem(data) { return request.post('/config-provider/items/update', data) },
  batchSaveItems(data) { return request.post('/config-provider/items/batch-save', data) },
  // Bindings
  getBindings(params) { return request.get('/config-provider/bindings/list', { params }) },
  createBinding(data) { return request.post('/config-provider/bindings/create', data) },
  deleteBinding(params) { return request.post('/config-provider/bindings/delete', null, { params }) },
  batchCreateBindings(data) { return request.post('/config-provider/bindings/batch-create', data) },
}
