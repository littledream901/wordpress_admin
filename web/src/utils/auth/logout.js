// 委托给 auth-manager，保持 @/utils 导入路径兼容
export {
  forceLogout,
  isForceLoggingOut,
  resetForceLogoutFlag,
  registerStopAllPollingHandler,
  unregisterStopAllPollingHandler,
} from '@/utils/auth-manager'
