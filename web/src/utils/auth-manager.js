import { request as http } from '@/utils/http'
import { getToken, getRefreshToken, setTokens, removeTokens } from '@/utils/auth'
import { router } from '@/router'
import { useUserStore, usePermissionStore } from '@/store'

// ── 全局状态 ──
let refreshing = false
let refreshPromise = null
let forceLoggingOut = false
let stopAllPollingHandlers = []

export function registerStopAllPollingHandler(fn) {
  if (typeof fn === 'function' && !stopAllPollingHandlers.includes(fn)) {
    stopAllPollingHandlers.push(fn)
  }
}

export function unregisterStopAllPollingHandler(fn) {
  stopAllPollingHandlers = stopAllPollingHandlers.filter(h => h !== fn)
}

export function isForceLoggingOut() {
  return forceLoggingOut
}

export function resetForceLogoutFlag() {
  forceLoggingOut = false
}

// ── refresh 成功后校验 userinfo ──
async function validateSessionByUserInfo() {
  try {
    await http.get('/base/userinfo', { skipAuthRefresh: true })
    return true
  } catch {
    return false
  }
}

// ── 尝试刷新 token（单飞模式，全局最多一个在飞） ──
export async function tryRefreshToken() {
  const rt = getRefreshToken()
  if (!rt) return false

  if (refreshing && refreshPromise) {
    return refreshPromise
  }

  refreshing = true
  refreshPromise = (async () => {
    try {
      const res = await http.post(
        '/base/refresh_token',
        { refresh_token: rt },
        { skipAuthRefresh: true }
      )

      const body = res && res.data ? res.data : null
      if (!body || body.code !== 200 || !body.data) {
        return false
      }

      const access = body.data.access_token
      const newRefresh = body.data.refresh_token
      if (!access || !newRefresh) {
        return false
      }

      setTokens(access, newRefresh)

      // 刷新成功后必须校验 userinfo
      const ok = await validateSessionByUserInfo()
      return ok
    } catch {
      return false
    } finally {
      refreshing = false
      refreshPromise = null
    }
  })()

  return refreshPromise
}

// ── 强制退出登录（全局闸门，防重入） ──
export async function forceLogout() {
  if (forceLoggingOut) return
  forceLoggingOut = true

  // 停止所有轮询
  for (const handler of stopAllPollingHandlers) {
    try { handler() } catch { /* ignore */ }
  }

  // 清空 tokens
  removeTokens()

  // 重置 stores
  try {
    usePermissionStore().resetPermission()
  } catch { /* store 未就绪 */ }

  try {
    useUserStore().$reset()
  } catch { /* store 未就绪 */ }

  // 跳转登录页
  if (router.currentRoute.value.path !== '/login') {
    await router.replace('/login')
  }
}
