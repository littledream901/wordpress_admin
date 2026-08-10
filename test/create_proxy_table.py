import asyncio
import os
from pathlib import Path
from tortoise import Tortoise
from dotenv import load_dotenv

async def create_table():
    """临时建表脚本 - 仅在 aerich 迁移链损坏时使用"""
    # 加载 .env 文件
    env_path = Path(__file__).parent.parent / '.env'
    load_dotenv(env_path)
    
    db_url = f"mysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    
    await Tortoise.init(
        config={
            'connections': {
                'default': db_url
            },
            'apps': {
                'models': {
                    'models': [],
                    'default_connection': 'default'
                }
            }
        }
    )
    
    conn = Tortoise.get_connection('default')
    
    sql = """
        CREATE TABLE IF NOT EXISTS `hubstudio_proxy_config` (
            `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
            `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
            `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '更新时间',
            `name` VARCHAR(128) NOT NULL COMMENT '代理配置名称',
            `code` VARCHAR(64) NOT NULL COMMENT '代理配置唯一编码',
            `description` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '代理配置描述',
            `proxy_type_name` VARCHAR(32) NOT NULL DEFAULT 'HTTP' COMMENT '代理类型',
            `proxy_host` VARCHAR(255) NOT NULL COMMENT '代理服务器地址',
            `proxy_port` INT NOT NULL COMMENT '代理端口',
            `proxy_account` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '代理账号',
            `proxy_password` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '代理密码',
            `reference_country_code` VARCHAR(8) NOT NULL DEFAULT 'US' COMMENT '参考国家代码',
            `reference_city` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '参考城市',
            `reference_region_code` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '参考区域/省份代码',
            `as_dynamic_type` INT NOT NULL DEFAULT 0 COMMENT '动态代理类型: 0=固定IP 1=动态IP',
            `ip_get_rule_type` INT NOT NULL DEFAULT 1 COMMENT 'IP获取规则类型',
            `link_code` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '代理提取链接或API代码',
            `ip_database_channel` INT NOT NULL DEFAULT 0 COMMENT 'IP数据库渠道',
            `ip_protocol_type` INT NOT NULL DEFAULT 0 COMMENT 'IP协议类型',
            `use_fixed_proxy` BOOL NOT NULL DEFAULT 1 COMMENT '是否使用固定代理配置',
            `status` VARCHAR(32) NOT NULL DEFAULT 'active' COMMENT '状态: active/disabled/testing',
            `priority` INT NOT NULL DEFAULT 0 COMMENT '优先级，数字越大优先级越高',
            `is_default` BOOL NOT NULL DEFAULT 0 COMMENT '是否为默认代理',
            `usage_count` INT NOT NULL DEFAULT 0 COMMENT '累计使用次数',
            `success_count` INT NOT NULL DEFAULT 0 COMMENT '成功次数',
            `last_used_at` DATETIME(6) NULL COMMENT '最后使用时间',
            `last_check_at` DATETIME(6) NULL COMMENT '最后健康检查时间',
            `provider_id` INT NOT NULL DEFAULT 0 COMMENT '绑定的 ConfigProvider ID，0 表示全局可用',
            UNIQUE KEY `uid_hubstudio_p_name` (`name`),
            UNIQUE KEY `uid_hubstudio_p_code` (`code`),
            KEY `idx_hubstudio_p_created` (`created_at`),
            KEY `idx_hubstudio_p_updated` (`updated_at`),
            KEY `idx_hubstudio_p_code` (`code`),
            KEY `idx_hubstudio_p_status` (`status`),
            KEY `idx_hubstudio_p_provider` (`provider_id`),
            KEY `idx_hubstudio_p_status_default` (`status`, `is_default`),
            KEY `idx_hubstudio_p_provider_status` (`provider_id`, `status`)
        ) CHARACTER SET utf8mb4 COMMENT='HubStudio 代理配置表';
    """
    
    await conn.execute_script(sql)
    print("Table hubstudio_proxy_config created successfully")
    
    await Tortoise.close_connections()

if __name__ == '__main__':
    asyncio.run(create_table())
