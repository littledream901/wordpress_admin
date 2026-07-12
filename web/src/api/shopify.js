import { request } from '@/utils'

export default {
  getSourceList: (params = {}) => request.get('/shopify/source/list', { params }),
  createSource: (data = {}) => request.post('/shopify/source/create', data),
  updateSource: (data = {}) => request.post('/shopify/source/update', data),
  deleteSource: (sourceId) => request.post(`/shopify/source/${sourceId}/delete`),
  collectSource: (sourceId) => request.post(`/shopify/source/${sourceId}/collect`),
  batchCreateSource: (items = []) => request.post('/shopify/source/batch-create', items),
  batchDeleteSource: (ids = []) => request.post('/shopify/source/batch-delete', ids),
  batchCollectSource: (ids = []) => request.post('/shopify/source/batch-collect', ids),

  getProductList: (params = {}) => request.get('/shopify/product/list', { params }),
  updateProduct: (data = {}) => request.post('/shopify/product/update', data),
  randomAssign: (data = {}) => request.post('/shopify/product/random-assign', data),
  batchRandomAssign: (data = {}) => request.post('/shopify/product/batch-random-assign', data),
  importProductToSite: (productId, data = {}) => request.post(`/shopify/product/${productId}/import-to-site`, data),
  batchImportToSite: (data = {}) => request.post('/shopify/product/batch-import', data),
  deleteProduct: (productId) => request.post(`/shopify/product/${productId}/delete`),
  batchDeleteProducts: (ids = []) => request.post('/shopify/product/batch-delete', { ids }),
}
