# 修复 site_id 字段缺失问题

## 问题描述
`site_pipeline_gmail_registration` 表缺少 `site_id` 字段，导致查询时出现错误：
```
tortoise.exceptions.OperationalError: (1054, "Unknown column 'site_id' in 'field list'")
```

## 解决方案

### 方案 1：直接执行 SQL（推荐，最快）

在服务器上连接数据库后执行：

```sql
-- 添加 site_id 列和索引
ALTER TABLE `site_pipeline_gmail_registration` 
ADD COLUMN `site_id` INT NULL COMMENT '关联站点ID' AFTER `domain`,
ADD INDEX `idx_site_id` (`site_id`);
```

**操作步骤：**
```bash
# 登录 MySQL
mysql -u用户名 -p

# 选择数据库
USE vue_fastapi_admin;

# 执行上述 SQL
```

### 方案 2：使用 SQL 文件

```bash
cd /opt/wordpress-admin
mysql -u用户名 -p数据库名 < migrations/manual/002_add_site_id_simple.sql
```

### 方案 3：使用 Python 脚本

```bash
cd /opt/wordpress-admin
python scripts/apply_site_id_migration.py
```

## 验证

执行以下 SQL 验证字段是否添加成功：

```sql
SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_COMMENT
FROM INFORMATION_SCHEMA.COLUMNS 
WHERE TABLE_SCHEMA = DATABASE() 
  AND TABLE_NAME = 'site_pipeline_gmail_registration' 
  AND COLUMN_NAME = 'site_id';
```

应该返回一行数据，显示 `site_id` 字段的信息。

## 预防措施

已更新迁移文件 `migrations/models/6_20260810120000_add_gmail_registration.py`，确保下次全新部署时会自动创建 `site_id` 字段。

## 重启服务

修复完成后重启 FastAPI 服务：

```bash
# Docker 环境
docker-compose restart

# 或者 systemd 服务
systemctl restart wordpress-admin
```
