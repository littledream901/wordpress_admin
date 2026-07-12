/**
 * 操作任务（Operation Job）类型声明
 *
 * 与后端 `operation_job` 模型对齐。
 */

/** 任务状态 */
export type JobStatus = 'pending' | 'running' | 'success' | 'failed' | 'cancelled'

/** 任务操作类型 */
export type JobActionType =
  | 'dns'
  | 'dynadot_ns'
  | 'redirect'
  | 'provision'
  | 'woo_import'
  | 'hub_create_env'
  | 'hub_create_account'
  | 'hub_update_env'
  | 'hub_website_control'
  | 'hub_gmc_check'

/** 操作任务实体 */
export interface OperationJob {
  id: number
  /** 关联资源类型 */
  resource_type: 'site'
  /** 关联资源 ID */
  resource_id: number
  /** 域名 */
  domain: string
  /** 操作类型 */
  action_type: JobActionType
  /** 任务状态 */
  status: JobStatus
  /** 当前步骤（如 "1/5"） */
  step?: string
  /** 总步骤数 */
  total_steps: number
  /** 任务负载 JSON */
  payload_json?: string
  /** 结果 JSON */
  result_json?: string
  /** 错误信息 */
  error_message?: string
  /** 批量任务 ID */
  batch_id?: string
  started_at?: string
  finished_at?: string
  created_at?: string
  updated_at?: string
}

/** HubStudio 任务实体（继承 OperationJob） */
export interface HubJob extends OperationJob {
  action_type: JobActionType & string
}

/** Agent 状态 */
export interface AgentStatus {
  agent_id: string
  online: boolean
  last_heartbeat?: string
}
