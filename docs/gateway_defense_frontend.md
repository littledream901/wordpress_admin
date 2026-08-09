# 网关防御功能 - 前端实现总结

## ✅ 已完成的前端功能

### 1. **API 接口封装**

#### 新建文件：`web/src/api/gateway-defense.js`
独立的网关防御 API 模块，包含：
- `deployGatewayDefense()` - 部署网关防御
- `batchDeployGatewayDefense()` - 批量部署
- `getGatewayCredentials()` - 获取凭证
- `getGatewayProviderInfo()` - 获取 Provider 信息
- `updateGatewayDefense()` - 更新配置

#### 集成到现有 API：`web/src/api/site-pipeline.js`
在站点流水线 API 中新增：
- 单站点操作方法（4个）
- 批量操作方法（1个）

### 2. **站点列表增强**

#### 新增"网关防御"状态列
```javascript
{ 
  title: '网关防御', 
  key: 'gateway_defense_status', 
  width: 90, 
  render: (r) => {
    // 未部署 → 灰色
    // 已部署 → 绿色
    // 失败 → 红色
  }
}
```

#### 新增操作按钮
在每行的操作列中新增"网关防御"按钮：
- 未部署时显示空心按钮
- 已部署时显示实心按钮（状态高亮）
- 点击打开部署弹窗

### 3. **部署弹窗组件**

#### 功能特性
✅ **站点信息展示**：域名、平台、防御类型
✅ **密钥来源选择**：
  - 自动生成（默认）
  - 手动输入
✅ **配置项**：
  - 网关地址（默认：`https://gateway.foxfingerlab.com`）
  - 失败模式（Open / Closed）
  - 注入 SDK（开关）
✅ **状态提示**：已部署站点显示部署时间和类型
✅ **操作按钮**：
  - 取消
  - 查看凭证（已部署时显示）
  - 部署/重新部署

#### 表单验证
- 手动输入密钥时，验证 `site_key` 和 `site_secret` 是否都已填写
- 网关地址必填

### 4. **凭证查看弹窗**

展示站点的网关凭证信息：
- 站点 ID
- 域名
- 站点密钥（`site_key`）
- 签名密钥（`site_secret`）
- 部署状态
- 防御类型
- 部署时间

### 5. **批量操作**

#### 批量操作菜单
在批量操作下拉菜单中新增：
```javascript
{ 
  label: '批量网关防御', 
  key: 'gateway-defense', 
  icon: 'mdi:shield-check', 
  permission: 'post/api/v1/site-pipeline/site/batch-gateway-defense' 
}
```

#### 批量部署逻辑
```javascript
async function executeBatchAction(action) {
  // ...
  if (action === 'gateway-defense') {
    res = await api.batchDeployGatewayDefense({
      site_ids: ids,
      gateway_url: batchGatewayUrl.value || 'https://gateway.foxfingerlab.com',
      fail_mode: 'open',
      sdk_inject: true,
    })
  }
  // ...
}
```

#### 批量配置输入
在批量操作确认对话框中新增：
```html
<n-form-item v-if="currentBatchAction === 'gateway-defense'" label="网关地址">
  <n-input v-model:value="batchGatewayUrl" placeholder="https://gateway.foxfingerlab.com" />
</n-form-item>
```

## 🎨 UI/UX 特点

### 1. **状态可视化**
- 使用 NTag 组件显示不同状态
- 颜色编码：灰色（未部署）、绿色（已部署）、红色（失败）

### 2. **渐进式表单**
- 密钥来源选择为"自动生成"时，隐藏密钥输入框
- 密钥来源选择为"手动输入"时，展开密钥输入框

### 3. **上下文提示**
- 部署前显示站点信息（域名、平台、防御类型）
- 配置项下方显示详细说明文字
- 已部署站点显示当前部署状态

### 4. **操作反馈**
- 部署按钮显示 loading 状态
- 成功/失败使用 message 提示
- 批量操作显示结果统计（成功 X 个，失败 X 个）

## 📊 交互流程

### 单站点部署流程
```
点击"网关防御"按钮
  ↓
打开部署弹窗
  ↓
选择密钥来源（自动生成/手动输入）
  ↓
配置网关地址、失败模式、SDK注入
  ↓
点击"部署"按钮
  ↓
显示 loading
  ↓
API 调用成功
  ↓
显示成功提示
  ↓
关闭弹窗，刷新列表
```

### 查看凭证流程
```
点击"网关防御"按钮（已部署的站点）
  ↓
打开部署弹窗
  ↓
点击"查看凭证"按钮
  ↓
调用 getGatewayCredentials API
  ↓
打开凭证查看弹窗
  ↓
显示完整凭证信息
```

### 批量部署流程
```
选择多个站点（勾选复选框）
  ↓
点击"批量操作"按钮
  ↓
选择"批量网关防御"
  ↓
输入网关地址
  ↓
点击"确认"按钮
  ↓
显示批量操作进度
  ↓
显示批量结果弹窗（成功/失败统计）
```

## 🔧 技术实现细节

### 1. **响应式数据**
```javascript
const showGatewayDefense = ref(false)
const showGatewayCredentials = ref(false)
const currentSite = ref(null)
const gatewayDeployLoading = ref(false)
const gatewayCredentials = ref(null)
const gatewayForm = reactive({...})
const batchGatewayUrl = ref('https://gateway.foxfingerlab.com')
```

### 2. **表单验证**
```javascript
if (gatewayForm.key_source === 'manual') {
  if (!gatewayForm.site_key || !gatewayForm.site_secret) {
    message.error('请输入完整的站点密钥和签名密钥')
    return
  }
}
```

### 3. **条件渲染**
```html
<template v-if="gatewayForm.key_source === 'manual'">
  <!-- 密钥输入表单 -->
</template>

<n-button 
  v-if="currentSite?.gateway_defense_status === 'deployed'" 
  @click="viewGatewayCredentials" 
  type="info"
>
  查看凭证
</n-button>
```

### 4. **权限控制**
```javascript
withDirectives(
  h(NButton, { 
    size: 'tiny', 
    type: 'error', 
    ghost: !gatewayOk, 
    onClick: () => openGatewayDefenseDialog(row) 
  }, { 
    default: () => '网关防御' 
  }), 
  [[vPermission, 'post/api/v1/site-pipeline/site/{site_id}/gateway-defense']]
)
```

## 📝 代码文件清单

### 修改的文件
1. ✅ `web/src/api/site-pipeline.js` - 新增网关防御 API 方法
2. ✅ `web/src/views/site-pipeline/site-list/index.vue` - 主要实现文件
   - 新增状态列
   - 新增操作按钮
   - 新增部署弹窗
   - 新增凭证查看弹窗
   - 新增批量操作逻辑
   - 新增 JavaScript 函数

### 新建的文件
1. ✅ `web/src/api/gateway-defense.js` - 独立的网关防御 API 模块

## 🎯 功能完整性检查

- ✅ 状态显示：列表中显示网关防御状态
- ✅ 单站点部署：弹窗中配置并部署
- ✅ 批量部署：批量操作菜单中支持
- ✅ 密钥管理：支持自动生成和手动输入
- ✅ 凭证查看：已部署站点可查看完整凭证
- ✅ 配置选项：网关地址、失败模式、SDK注入
- ✅ 权限控制：所有操作都接入权限系统
- ✅ 错误处理：完整的错误提示和反馈
- ✅ 加载状态：按钮显示 loading
- ✅ 用户体验：清晰的提示和反馈

## 🚀 使用说明

### 单站点部署
1. 在站点列表中找到目标站点
2. 点击操作列中的"网关防御"按钮
3. 选择密钥来源（自动生成/手动输入）
4. 配置网关地址和其他选项
5. 点击"部署"按钮
6. 等待部署完成
7. 查看成功提示

### 查看凭证
1. 对于已部署的站点，点击"网关防御"按钮
2. 在部署弹窗中，点击"查看凭证"按钮
3. 查看站点密钥和签名密钥
4. 可复制凭证用于其他用途

### 批量部署
1. 勾选多个站点
2. 点击"批量操作"按钮
3. 选择"批量网关防御"
4. 输入网关地址
5. 点击"确认"按钮
6. 查看批量结果统计

## ⚠️ 注意事项

1. **密钥安全**：手动输入的密钥会通过 HTTPS 传输，不会在前端存储
2. **状态刷新**：部署完成后会自动刷新列表，展示最新状态
3. **批量操作**：批量部署时所有站点使用相同的网关地址和配置
4. **权限验证**：所有操作都会进行权限验证，无权限的按钮会被隐藏
5. **错误提示**：部署失败时会显示详细的错误信息

## 📸 界面预览

### 列表视图
- 新增"网关防御"列，显示状态标签
- 操作列中新增"网关防御"按钮

### 部署弹窗
- 顶部：站点信息提示框（蓝色）
- 中间：配置表单（网关地址、密钥来源、失败模式、SDK注入）
- 底部：操作按钮（取消、查看凭证、部署）

### 凭证查看弹窗
- 使用 Descriptions 组件展示凭证信息
- 站点密钥和签名密钥使用 code 样式显示

## 🎉 总结

前端功能已全部实现，包括：
- ✅ API 接口封装（7个方法）
- ✅ 状态列显示
- ✅ 操作按钮（单站点）
- ✅ 部署弹窗（完整表单）
- ✅ 凭证查看弹窗
- ✅ 批量操作支持
- ✅ 权限控制集成
- ✅ 错误处理和反馈

与后端 API 完全对接，可直接使用！🚀
