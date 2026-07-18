import { request } from '@/utils'

export default {
  getMenus: (params = {}) => request.get('/menu/list', { params }),
  createMenu: (data = {}) => request.post('/menu/create', data),
  updateMenu: (data = {}) => request.post('/menu/update', data),
  deleteMenu: (params = {}) => request.delete('/menu/delete', { params }),
  deleteMenuCascade: (params = {}) => request.delete('/menu/delete', { params: { ...params, cascade: true } }),
}
