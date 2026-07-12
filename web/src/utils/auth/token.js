import { lStorage } from '@/utils'

const TOKEN_CODE = 'access_token'
const REFRESH_TOKEN_CODE = 'refresh_token'

export function getToken() {
  return lStorage.get(TOKEN_CODE)
}

export function setToken(token) {
  lStorage.set(TOKEN_CODE, token)
}

export function removeToken() {
  lStorage.remove(TOKEN_CODE)
}

export function getRefreshToken() {
  return lStorage.get(REFRESH_TOKEN_CODE)
}

export function setRefreshToken(token) {
  lStorage.set(REFRESH_TOKEN_CODE, token)
}

export function removeRefreshToken() {
  lStorage.remove(REFRESH_TOKEN_CODE)
}

export function setTokens(accessToken, refreshToken) {
  setToken(accessToken)
  setRefreshToken(refreshToken)
}

export function removeTokens() {
  removeToken()
  removeRefreshToken()
}
