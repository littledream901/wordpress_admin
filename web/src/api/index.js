import { request } from '@/utils'

// 按后端模块拆分，导入各模块再聚合
import authApi from './auth'
import userApi from './user'
import roleApi_ from './role'
import menuApi_ from './menu'
import apiApi_ from './api'
import deptApi_ from './dept'

// auditlog / accounts 保持内联（调用量小）
const auditlogApi = {
  getAuditLogList: (params = {}) => request.get('/auditlog/list', { params }),
}

const accountsApi = {
  getAccountList: (params = {}) => request.get('/account/list', { params }),
  createAccount: (data = {}) => request.post('/account/create', data),
  updateAccount: (data = {}) => request.post('/account/update', data),
  deleteAccount: (params = {}) => request.delete('/account/delete', { params }),
}

// 聚合导出：保持 import api from '@/api' 兼容所有旧代码
export default {
  ...authApi,
  ...userApi,
  ...roleApi_,
  ...menuApi_,
  ...apiApi_,
  ...deptApi_,
  ...auditlogApi,
  ...accountsApi,
}

// 按模块命名导出（推荐新代码使用）
export { default as authApi } from './auth'
export { default as userApi } from './user'
export { default as roleApi } from './role'
export { default as menuApi } from './menu'
export { default as apiApi } from './api'
export { default as deptApi } from './dept'
export { default as shopifyApi } from './shopify'
export { default as sitePipelineApi } from './site-pipeline'
export { default as gmailApi } from './gmail'
export { default as configProviderApi } from './configProvider'
export { default as importJobApi } from './importJob'
export { default as operationJobApi } from './operationJob'
export { default as onepanelMonitorApi } from './onepanel-monitor'
export { default as recycleBinApi } from './recycleBin'
