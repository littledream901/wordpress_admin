import { getToken } from '@/utils'
import { tryRefreshToken, forceLogout, isForceLoggingOut } from '@/utils/auth-manager'
import { resolveResError } from './helpers'
import axios from 'axios'

// ── 请求拦截器 ──
export function reqResolve(config) {
  // 全局退出闸门：拦截所有新请求
  if (isForceLoggingOut()) {
    return Promise.reject({ code: 0, message: '', __forceLogout: true })
  }

  // 不需要 token 的请求直接放行
  if (config.noNeedToken) {
    return config
  }

  const token = getToken()
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }

  return config
}

export function reqReject(error) {
  return Promise.reject(error)
}

// ── 成功响应 ──
export function resResolve(response) {
  const { data, status, statusText, config } = response

  // blob / arraybuffer 等二进制响应跳过 code 检查
  if (config.responseType === 'blob' || config.responseType === 'arraybuffer') {
    return Promise.resolve(data)
  }

  if (data?.code !== 200) {
    const code = data?.code ?? status
    const message = resolveResError(code, data?.msg ?? statusText)
    window.$message?.error(message, { keepAliveOnHover: true })
    return Promise.reject({ code, message, error: data || response })
  }

  return Promise.resolve(data)
}

// ── 错误响应 ──
export async function resReject(error) {
  // 由请求拦截器闸门拦截的请求，静默丢弃
  if (error?.__forceLogout) {
    return Promise.reject(error)
  }

  // 无 response 的网络错误
  if (!error || !error.response) {
    const code = error?.code
    const message = resolveResError(code, error.message)
    window.$message?.error(message)
    return Promise.reject({ code, message, error })
  }

  const { data, status, config } = error.response

  // 全局退出进行中：静默拒绝
  if (isForceLoggingOut()) {
    return Promise.reject({ code: status, message: '', __forceLogout: true })
  }

  // skipAuthRefresh + 401 → 会话已死，直接退出
  if (config?.skipAuthRefresh && (data?.code === 401 || status === 401)) {
    await forceLogout()
    return Promise.reject({
      code: 401,
      message: '登录已失效，请重新登录',
      error: error.response?.data || error.response,
    })
  }

  // 401 → 委托 auth-manager 刷新 → 重放或退出
  if (data?.code === 401 || status === 401) {
    if (config._retry) {
      await forceLogout()
      return Promise.reject({
        code: 401,
        message: '登录已失效，请重新登录',
        error: error.response?.data || error.response,
      })
    }

    const refreshed = await tryRefreshToken()
    if (refreshed) {
      config._retry = true
      config.headers = config.headers || {}
      config.headers.Authorization = `Bearer ${getToken()}`
      return new Promise((resolve) => {
        resolve(axios(config))
      })
    }

    // 刷新失败 → 退出（tryRefreshToken 内部已做 userinfo 校验）
    await forceLogout()
    return Promise.reject({
      code: 401,
      message: '登录已过期，请重新登录',
      error: error.response?.data || error.response,
    })
  }

  // 其他错误：显示提示
  const code = data?.code ?? status
  const message = resolveResError(code, data?.msg ?? error.message)
  window.$message?.error(message, { keepAliveOnHover: true })
  return Promise.reject({ code, message, error: error.response?.data || error.response })
}
