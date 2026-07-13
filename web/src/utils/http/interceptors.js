import { getToken, getRefreshToken, setTokens } from '@/utils'
import { resolveResError } from './helpers'
import { useUserStore } from '@/store'
import api from '@/api'
import axios from 'axios'

let isRefreshing = false
let refreshSubscribers = []

function onRefreshed(newToken) {
  refreshSubscribers.forEach((cb) => cb(newToken))
  refreshSubscribers = []
}

function addRefreshSubscriber(cb) {
  refreshSubscribers.push(cb)
}

async function tryRefreshToken() {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return false

  try {
    const res = await api.refreshToken({ refresh_token: refreshToken })
    setTokens(res.data.access_token, res.data.refresh_token)
    return res.data.access_token
  } catch {
    return false
  }
}

export function reqResolve(config) {
  // 处理不需要token的请求
  if (config.noNeedToken) {
    return config
  }

  const token = getToken()
  if (token) {
    config.headers.Authorization = config.headers.Authorization || `Bearer ${token}`
  }

  return config
}

export function reqReject(error) {
  return Promise.reject(error)
}

export function resResolve(response) {
  const { data, status, statusText, config } = response
  // blob 等二进制响应跳过 code 检查，直接透传
  if (config.responseType === 'blob' || config.responseType === 'arraybuffer') {
    return Promise.resolve(data)
  }
  if (data?.code !== 200) {
    const code = data?.code ?? status
    /** 根据code处理对应的操作，并返回处理后的message */
    const message = resolveResError(code, data?.msg ?? statusText)
    window.$message?.error(message, { keepAliveOnHover: true })
    return Promise.reject({ code, message, error: data || response })
  }
  return Promise.resolve(data)
}

export async function resReject(error) {
  if (!error || !error.response) {
    const code = error?.code
    /** 根据code处理对应的操作，并返回处理后的message */
    const message = resolveResError(code, error.message)
    window.$message?.error(message)
    return Promise.reject({ code, message, error })
  }
  const { data, status, config } = error.response

  if (data?.code === 401 && !config._retry) {
    // 尝试用 refresh_token 刷新
    if (!isRefreshing) {
      isRefreshing = true
      const newToken = await tryRefreshToken()
      isRefreshing = false

      if (newToken) {
        onRefreshed(newToken)
        config._retry = true
        config.headers.Authorization = `Bearer ${newToken}`
        return new Promise((resolve) => {
          resolve(axios(config))
        })
      }
    }

    // 已在刷新中，排队等待
    if (isRefreshing) {
      return new Promise((resolve) => {
        addRefreshSubscriber((newToken) => {
          config._retry = true
          config.headers.Authorization = `Bearer ${newToken}`
          resolve(axios(config))
        })
      })
    }

    // 刷新失败，登出
    try {
      const userStore = useUserStore()
      userStore.logout()
    } catch {
      return
    }
    return Promise.reject({ code: 401, message: '登录已过期', error: error.response?.data || error.response })
  }

  // 后端返回的response数据
  const code = data?.code ?? status
  const message = resolveResError(code, data?.msg ?? error.message)
  window.$message?.error(message, { keepAliveOnHover: true })
  return Promise.reject({ code, message, error: error.response?.data || error.response })
}
