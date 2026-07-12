/**
 * 站点（Site Pipeline）类型声明
 *
 * 与后端 `site_pipeline` 模型对齐。
 */

/** 站点状态 */
export type SiteStatus = 'pending' | 'provisioning' | 'ready' | 'error' | 'deleted'

/** 站点实体 */
export interface Site {
  id: number
  domain: string
  status: SiteStatus
  /** 旧源域名（域名替换时用） */
  source_domain?: string
  /** 模板备份路径 */
  template_backup_path?: string
  /** 数据库备份路径 */
  db_backup_path?: string
  /** 建站使用的 1Panel provider ID */
  op_provider_id?: number
  /** 建站使用的 Cloudflare provider ID */
  cf_provider_id?: number
  /** 建站使用的 HubStudio provider ID */
  hub_provider_id?: number
  /** 流水线日志（JSON 数组字符串） */
  pipeline_log?: string
  /** NS 记录 */
  ns_records?: string
  /** Feed 信息 */
  feed_info?: string
  created_at?: string
  updated_at?: string
}

/** 创建站点请求 */
export interface CreateSiteParams {
  domain: string
  source_domain?: string
  template_backup_path?: string
  db_backup_path?: string
  op_provider_id?: number
  cf_provider_id?: number
  hub_provider_id?: number
}

/** 更新站点请求 */
export interface UpdateSiteParams extends Partial<CreateSiteParams> {
  id: number
  status?: SiteStatus
}

/** 批量 HubStudio 分发参数 */
export interface HubDispatchParams {
  site_ids: number[]
  job_type: 'create_env' | 'create_account' | 'update_env' | 'website_control' | 'gmc_check'
}

/** 批量重定向参数 */
export interface BatchRedirectParams {
  site_ids: number[]
  target_url: string
}

/** 批量 Dynadot NS 参数 */
export interface BatchDynadotNsParams {
  site_ids: number[]
  ns_list: string
}
