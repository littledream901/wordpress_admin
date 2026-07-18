# FastAPI+Vue 后台管理项目编码规范
适用目录：app/、web/src/
核心目标：保持分层架构、复用公共组件、抽离通用工具函数、遵循RBAC权限规范

## 一、后端 FastAPI 编码规范
### 目录分层原则
1. api/v1/：仅做路由注册、参数基础校验、调用 controllers，禁止写核心业务逻辑
    - 每个模块单独路由文件：users.py / roles.py  等
    - 统一前缀 /api/v1/，遵循RESTful风格 GET/POST/PUT/DELETE
    - 必须使用 core 权限依赖做接口鉴权
2. controllers/：业务主逻辑层，处理CRUD、参数组装、调用models/services/utils
    - 禁止直接写第三方接口请求、通用格式化、数据库基础方法
    - 公共CRUD复用 core 基类，减少重复增删改查代码
3. models/：仅存放 Tortoise ORM 数据表模型，定义字段、索引、基础约束，不写业务逻辑
4. schemas/：Pydantic 请求/响应模型，做数据校验、序列化、类型约束
    - 区分 Create / Update / Response 三类Schema，统一错误返回格式
5. services/：第三方外部服务（Shopify、Gmail、Cloudflare、Dynadot、HubStudio等）
    - 每个外部系统单独service，封装请求、异常处理、重试逻辑，禁止散写在controller里
    - providers/目录存放通用第三方SDK封装
6. core/：全局基础能力，不要随意修改
    - 认证、RBAC权限校验、全局异常、日志、基础CRUD类、中间件
7. utils/：通用纯工具函数（日期、金额、脱敏、正则、加解密、导出等）
    - 可复用通用逻辑必须抽入 utils/，禁止复制粘贴到controller/路由
    - 纯函数、增加类型注解和文档字符串
8. settings/：全局配置、环境变量读取，密钥、敏感信息放入环境变量，禁止硬编码
9. agent/：HubStudio Agent独立进程代码，与主服务代码做边界隔离
10. migrations/：Aerich数据库迁移，不要手动修改迁移文件，通过命令生成
11. auditlog：统一审计日志埋点，关键操作必须记录用户/IP/操作内容

### 后端禁止项
- ❌ 在api路由内写长业务逻辑、数据库查询、第三方接口调用
- ❌ 硬编码密钥、地址、第三方token，统一从settings/env读取
- ❌ 绕过core权限校验直接写接口
- ❌ 重复实现通用CRUD、校验、格式化代码
- ❌ 直接修改core基类，优先继承/扩展而非改动源码

## 二、前端 Vue 编码规范
### 目录分层原则
1. components/
    - 公共通用组件放入 `components/common/`：表格、弹窗、表单、搜索栏、状态标签等全局控件，可配置props，不硬编码业务字段
    - 业务模块组件放入 `components/business/`，与views页面解耦
    - 新增页面优先复用通用组件，不重复写基础弹窗/表单/表格
    - 使用 @/ 别名导入，禁止深层相对路径 import
2. api/：统一axios请求封装，按后端模块拆分（user.ts、role.ts、pipeline.ts等）
    - 统一请求/响应拦截器、token鉴权、错误处理
    - 禁止页面直接裸发axios请求
3. views/：页面视图，仅负责渲染布局、绑定事件、调用api/pinia
    - 复杂表单/列表逻辑抽入hooks，不要堆积在vue单文件中
    - 与后端模块一一对应：用户/角色/菜单/流水线/Shopify/任务中心等
4. router/：动态路由，由后端菜单接口生成，不写死路由
5. store/：Pinia全局状态（用户信息、权限、全局配置）
6. 通用工具：格式化、校验、导出等抽入web/src/utils/

### 前端禁止项
- ❌ 页面内复制通用表单、弹窗、表格模板
- ❌ 直接硬编码接口地址、token、第三方密钥
- ❌ 在模板/script中写大量通用格式化/校验逻辑
- ❌ 全局样式污染基础公共组件

## 三、整体代码审查规则
1. AI生成代码时先检索现有utils、公共组件、service封装，优先复用再新增代码
2. 新增功能遵循：先建schema/model → 写service/utils → controller → api路由 → 前端api/hook/view
3. 新增数据库表必须创建Tortoise模型并生成Aerich迁移
4. 新增接口默认增加RBAC权限校验、审计日志埋点
5. 保持JavaScript/Pydantic类型完整性，完善注释
6. 改动后保证可正常运行：数据库迁移、格式检查、基础接口验证


## 四、指令用法
- 重构代码指令：遵循本项目规范重构代码，抽离通用工具函数并复用公共组件
- 新增页面指令：按现有后台模板结构创建页面，接入对应v1接口，复用公共表单/表格组件
- 接口新增指令：按v1模块结构创建路由、schema、controller，增加权限校验和审计日志