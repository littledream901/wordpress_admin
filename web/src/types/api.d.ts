/**
 * API 通用类型声明
 *
 * 与后端 `app/core/exceptions.py` ErrorCode 和 JSON 响应格式对齐。
 * 此文件为 .d.ts 声明文件，不影响现有 JS 运行，仅提供 IDE 智能提示。
 */

/** 后端 ErrorCode 枚举值（与 app/core/exceptions.py 同步） */
export type ErrorCode = number

/** 通用 API 响应包装 */
export interface ApiResponse<T = any> {
  code: number
  msg: string
  data: T
  /** 业务错误码（失败时由后端统一注入） */
  error_code?: ErrorCode | null
}

/** 分页请求参数 */
export interface PaginationParams {
  page?: number
  page_size?: number
}

/** 分页响应 */
export interface PaginatedData<T> {
  items: T[]
  total: number
}
