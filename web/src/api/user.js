import { request } from '@/utils'

export default {
  getUserList: (params = {}) => request.get('/user/list', { params }),
  getUserById: (params = {}) => request.get('/user/get', { params }),
  createUser: (data = {}) => request.post('/user/create', data),
  updateUser: (data = {}) => request.post('/user/update', data),
  deleteUser: (params = {}) => request.delete('/user/delete', { params }),
  resetPassword: (data = {}) => request.post('/user/reset_password', data),
  uploadAvatar: (formData) => request.post('/user/avatar/upload', formData),
  setAvatarUrl: (data) => request.post('/user/avatar/url', data),
}
