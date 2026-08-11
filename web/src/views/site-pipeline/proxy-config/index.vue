<template>
  <CommonPage show-footer>
    <template #action>
      <n-space>
        <n-button type="primary" @click="handleAdd">
          <TheIcon icon="material-symbols:add" :size="18" class="mr-5" />
          新增代理
        </n-button>
        <n-button type="info" @click="showBatchImport = true">
          <TheIcon icon="material-symbols:upload" :size="18" class="mr-5" />
          批量导入
        </n-button>
        <n-button
          type="error"
          :disabled="!checkedRowKeys.length"
          @click="handleBatchDelete"
        >
          <TheIcon icon="material-symbols:delete-outline" :size="18" class="mr-5" />
          批量删除
        </n-button>
        <n-button
          type="warning"
          :disabled="!checkedRowKeys.length"
          @click="handleBatchCheck"
        >
          <TheIcon icon="material-symbols:network-check" :size="18" class="mr-5" />
          批量检测
        </n-button>
        <n-button
          type="default"
          :disabled="!checkedRowKeys.length"
          @click="handleBatchUnassign"
        >
          <TheIcon icon="material-symbols:link-off" :size="18" class="mr-5" />
          批量取消代理
        </n-button>
      </n-space>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="api.getList"
      :scroll-x="1600"
      :page-size="50"
    >
      <template #queryBar>
        <QueryBarItem label="状态" :label-width="50">
          <n-select
            v-model:value="queryItems.status"
            clearable
            :options="[
              { label: '激活', value: 'active' },
              { label: '禁用', value: 'disabled' },
              { label: '测试', value: 'testing' },
            ]"
            class="!w-120"
          />
        </QueryBarItem>
        <QueryBarItem label="搜索" :label-width="50">
          <n-input
            v-model:value="queryItems.keyword"
            clearable
            placeholder="代理地址或描述"
            class="!w-200"
          />
        </QueryBarItem>
      </template>
    </CrudTable>

    <!-- 批量导入弹窗 -->
    <n-modal
      v-model:show="showBatchImport"
      preset="card"
      title="批量导入代理"
      class="w-600"
      :segmented="{ content: 'soft', footer: 'soft' }"
    >
      <n-form label-placement="left" label-width="120">
        <n-form-item label="粘贴代理列表">
          <n-input
            v-model:value="batchImportText"
            type="textarea"
            placeholder="每行一条，格式：host:port:account:password&#10;示例：163.123.201.136:5921:user:pass"
            :rows="10"
          />
        </n-form-item>
        <n-alert type="info" :bordered="false" class="mb-10">
          格式说明：每行一条代理，格式为 <strong>host:port:account:password</strong><br />
          示例：163.123.201.136:5921:powygrwn:mbe5zxysoih3
        </n-alert>
        <n-form-item label="代理类型">
          <n-select
            v-model:value="batchImportForm.proxy_type_name"
            :options="[
              { label: 'HTTP', value: 'HTTP' },
              { label: 'HTTPS', value: 'HTTPS' },
              { label: 'SOCKS5', value: 'SOCKS5' },
            ]"
          />
        </n-form-item>
        <n-form-item label="国家代码">
          <n-input v-model:value="batchImportForm.reference_country_code" placeholder="如 US" />
        </n-form-item>
        <n-form-item label="城市">
          <n-input v-model:value="batchImportForm.reference_city" placeholder="如 New York" />
        </n-form-item>
        <n-form-item label="区域代码">
          <n-input v-model:value="batchImportForm.reference_region_code" placeholder="如 CA" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showBatchImport = false">取消</n-button>
          <n-button type="primary" :loading="importing" @click="handleBatchImport">导入</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 新增/编辑弹窗 -->
    <n-modal
      v-model:show="showEditModal"
      preset="card"
      :title="editId ? '编辑代理' : '新增代理'"
      class="w-700"
      :segmented="{ content: 'soft', footer: 'soft' }"
    >
      <n-form
        ref="editFormRef"
        :model="editForm"
        :rules="editRules"
        label-placement="left"
        label-width="120"
      >
        <n-form-item label="描述" path="description">
          <n-input v-model:value="editForm.description" placeholder="代理配置描述" />
        </n-form-item>
        <n-form-item label="代理地址" path="proxy_host">
          <n-input v-model:value="editForm.proxy_host" placeholder="如 163.123.201.136" />
        </n-form-item>
        <n-form-item label="代理端口" path="proxy_port">
          <n-input-number
            v-model:value="editForm.proxy_port"
            :min="1"
            :max="65535"
            placeholder="如 5921"
            class="w-full"
          />
        </n-form-item>
        <n-form-item label="账号">
          <n-input v-model:value="editForm.proxy_account" placeholder="代理账号" />
        </n-form-item>
        <n-form-item label="密码">
          <n-input v-model:value="editForm.proxy_password" type="password" show-password-on="click" placeholder="代理密码" />
        </n-form-item>
        <n-form-item label="代理类型">
          <n-select
            v-model:value="editForm.proxy_type_name"
            :options="[
              { label: 'HTTP', value: 'HTTP' },
              { label: 'HTTPS', value: 'HTTPS' },
              { label: 'SOCKS5', value: 'SOCKS5' },
            ]"
          />
        </n-form-item>
        <n-form-item label="国家代码">
          <n-input v-model:value="editForm.reference_country_code" placeholder="如 US" />
        </n-form-item>
        <n-form-item label="城市">
          <n-input v-model:value="editForm.reference_city" placeholder="如 New York" />
        </n-form-item>
        <n-form-item label="区域代码">
          <n-input v-model:value="editForm.reference_region_code" placeholder="如 CA" />
        </n-form-item>
        <n-form-item label="状态">
          <n-select
            v-model:value="editForm.status"
            :options="[
              { label: '激活', value: 'active' },
              { label: '禁用', value: 'disabled' },
              { label: '测试', value: 'testing' },
            ]"
          />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showEditModal = false">取消</n-button>
          <n-button type="primary" :loading="saving" @click="handleSave">保存</n-button>
        </n-space>
      </template>
    </n-modal>

  </CommonPage>
</template>

<script setup>
import { h, onMounted, onActivated, ref, computed } from 'vue'
import { NButton, NSpace, NTag, NCheckbox, useMessage } from 'naive-ui'
import api from '@/api/hubstudio-proxy'
import { formatDateTime } from '@/utils'

const message = useMessage()
const $table = ref(null)

const queryItems = ref({
  status: '',
  keyword: '',
})

const checkedRowKeys = ref([])

const checkedAll = computed({
  get: () => {
    const rows = $table.value?.tableData || []
    return rows.length > 0 && checkedRowKeys.value.length === rows.length
  },
  set: (v) => {
    const rows = $table.value?.tableData || []
    if (v) checkedRowKeys.value = rows.map((r) => r.id)
    else checkedRowKeys.value = []
  },
})

const columns = [
  {
    title: () => h(NCheckbox, { checked: checkedAll.value, onUpdateChecked: (v) => { checkedAll.value = v } }),
    key: 'select',
    width: 44,
    render: (row) => h(NCheckbox, {
      checked: checkedRowKeys.value.includes(row.id),
      onUpdateChecked: (v) => {
        if (v) checkedRowKeys.value = [...checkedRowKeys.value, row.id]
        else checkedRowKeys.value = checkedRowKeys.value.filter((k) => k !== row.id)
      },
    }),
  },
  { key: 'id', title: 'ID', width: 80, ellipsis: { tooltip: true } },
  {
    key: 'proxy',
    title: '代理地址',
    width: 200,
    render: (row) => `${row.proxy_host}:${row.proxy_port}`,
  },
  { key: 'proxy_account', title: '账号', width: 150, ellipsis: { tooltip: true } },
  { key: 'description', title: '描述', width: 200, ellipsis: { tooltip: true } },
  {
    key: 'status',
    title: '状态',
    width: 90,
    render: (row) => {
      const statusMap = {
        active: { label: '激活', type: 'success' },
        disabled: { label: '禁用', type: 'error' },
        testing: { label: '测试', type: 'warning' },
      }
      const s = statusMap[row.status] || { label: row.status, type: 'default' }
      return h(NTag, { type: s.type, size: 'small' }, { default: () => s.label })
    },
  },
  {
    key: 'assigned_site',
    title: '分配站点',
    width: 200,
    render: (row) => {
      if (!row.assigned_site) {
        return h('span', { style: { color: '#999' } }, '未分配')
      }
      return h('div', [
        h('div', { style: { fontWeight: 'bold' } }, row.assigned_site.domain),
        h('div', { style: { fontSize: '12px', color: '#999' } }, `ID: ${row.assigned_site.id}`)
      ])
    },
  },
  {
    key: 'location',
    title: '地理位置',
    width: 180,
    render: (row) => {
      const parts = []
      if (row.reference_country_code) parts.push(row.reference_country_code)
      if (row.reference_region_code) parts.push(row.reference_region_code)
      if (row.reference_city) parts.push(row.reference_city)
      return parts.length > 0 ? parts.join(' / ') : '-'
    },
  },
  {
    key: 'actions',
    title: '操作',
    width: 200,
    fixed: 'right',
    render: (row) =>
      h(
        NSpace,
        {},
        {
          default: () => [
            h(
              NButton,
              { size: 'small', onClick: () => handleEdit(row) },
              { default: () => '编辑' }
            ),
            h(
              NButton,
              { size: 'small', type: 'info', onClick: () => handleCheckSingle(row) },
              { default: () => '检测' }
            ),
            h(
              NButton,
              { size: 'small', type: 'error', onClick: () => handleDelete(row) },
              { default: () => '删除' }
            ),
          ],
        }
      ),
  },
]

// 批量导入
const showBatchImport = ref(false)
const batchImportText = ref('')
const importing = ref(false)
const batchImportForm = ref({
  proxy_type_name: 'HTTP',
  reference_country_code: 'US',
  reference_city: '',
  reference_region_code: '',
  as_dynamic_type: 0,
  ip_get_rule_type: 1,
})

async function handleBatchImport() {
  if (!batchImportText.value.trim()) {
    message.warning('请粘贴代理列表')
    return
  }
  importing.value = true
  try {
    const res = await api.batchImport({
      raw_text: batchImportText.value,
      ...batchImportForm.value,
    })
    const d = res.data
    message.success(
      `导入完成：成功 ${d.success_count} 条，失败 ${d.failed_count} 条`
    )
    if (d.errors && d.errors.length > 0) {
      console.warn('导入失败详情：', d.errors)
    }
    showBatchImport.value = false
    batchImportText.value = ''
    $table.value?.handleSearch()
  }
  catch (error) {
    console.error('批量导入失败：', error)
  }
  finally {
    importing.value = false
  }
}

// 批量删除
async function handleBatchDelete() {
  if (!checkedRowKeys.value.length) {
    message.warning('请选择要删除的代理')
    return
  }
  
  window.$dialog.warning({
    title: '批量删除确认',
    content: `确定要删除选中的 ${checkedRowKeys.value.length} 条代理吗？删除后将进入回收站。`,
    positiveText: '确定',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.batchDelete(checkedRowKeys.value)
        message.success('批量删除成功')
        checkedRowKeys.value = []
        $table.value?.handleSearch()
      }
      catch (error) {
        console.error('批量删除失败：', error)
      }
    },
  })
}

// 批量检测
async function handleBatchCheck() {
  if (!checkedRowKeys.value.length) {
    message.warning('请选择要检测的代理')
    return
  }
  
  const loading = message.loading('正在检测代理连通性，请稍候...', { duration: 0 })
  try {
    const res = await api.batchCheck(checkedRowKeys.value)
    const d = res.data
    loading.destroy()
    message.success(
      `检测完成：成功 ${d.success_count} 条，失败 ${d.failed_count} 条`
    )
    $table.value?.handleSearch()
  }
  catch (error) {
    loading.destroy()
    console.error('批量检测失败：', error)
  }
}

// 批量取消代理
async function handleBatchUnassign() {
  if (!checkedRowKeys.value.length) {
    message.warning('请选择要取消分配的代理')
    return
  }
  
  window.$dialog.warning({
    title: '批量取消代理确认',
    content: `确定要取消选中的 ${checkedRowKeys.value.length} 条代理的站点分配吗？`,
    positiveText: '确定',
    negativeText: '取消',
    onPositiveClick: async () => {
      const loading = message.loading('正在取消分配，请稍候...', { duration: 0 })
      try {
        const res = await api.batchUnassign(checkedRowKeys.value)
        const d = res.data
        loading.destroy()
        message.success(
          `取消完成：成功 ${d.success_count} 条，失败 ${d.failed_count} 条`
        )
        checkedRowKeys.value = []
        $table.value?.handleSearch()
      }
      catch (error) {
        loading.destroy()
        console.error('批量取消分配失败：', error)
      }
    },
  })
}

// 单条检测
async function handleCheckSingle(row) {
  const loading = message.loading(`正在检测代理 ${row.proxy_host}:${row.proxy_port}...`, { duration: 0 })
  try {
    const res = await api.checkProxy(row.id)
    const result = res.data
    loading.destroy()
    
    if (result.status === 'success') {
      // 构建地理位置信息字符串
      const geoInfo = [
        result.detected_ip ? `IP: ${result.detected_ip}` : '',
        result.detected_country ? `国家/地区: ${result.detected_country}` : '',
        result.detected_region ? `州/省: ${result.detected_region}` : '',
        result.detected_city ? `城市: ${result.detected_city}` : '',
        result.detected_timezone ? `时区: ${result.detected_timezone}` : '',
      ].filter(Boolean).join('; ')
      
      const successMsg = geoInfo 
        ? `✓ 连接测试成功! ${geoInfo}` 
        : `检测成功！响应时间: ${result.response_time}ms`
      
      message.success(successMsg, { duration: 8000 })
    }
    else {
      message.error(`检测失败: ${result.error_message || result.status}`)
    }
    $table.value?.handleSearch()
  }
  catch (error) {
    loading.destroy()
    console.error('检测失败：', error)
  }
}

// 查看分配的站点
// 新增/编辑
const showEditModal = ref(false)
const editId = ref(null)
const editFormRef = ref(null)
const saving = ref(false)
const editForm = ref({
  description: '',
  proxy_host: '',
  proxy_port: null,
  proxy_account: '',
  proxy_password: '',
  proxy_type_name: 'HTTP',
  reference_country_code: 'US',
  reference_city: '',
  reference_region_code: '',
  status: 'active',
})

const editRules = {
  proxy_host: { required: true, message: '请输入代理地址', trigger: 'blur' },
  proxy_port: { required: true, type: 'number', message: '请输入代理端口', trigger: 'blur' },
}

function handleAdd() {
  editId.value = null
  editForm.value = {
    description: '',
    proxy_host: '',
    proxy_port: null,
    proxy_account: '',
    proxy_password: '',
    proxy_type_name: 'HTTP',
    reference_country_code: 'US',
    reference_city: '',
    reference_region_code: '',
    status: 'active',
  }
  showEditModal.value = true
}

function handleEdit(row) {
  editId.value = row.id
  editForm.value = {
    description: row.description || '',
    proxy_host: row.proxy_host,
    proxy_port: row.proxy_port,
    proxy_account: row.proxy_account || '',
    proxy_password: row.proxy_password || '',
    proxy_type_name: row.proxy_type_name || 'HTTP',
    reference_country_code: row.reference_country_code || 'US',
    reference_city: row.reference_city || '',
    reference_region_code: row.reference_region_code || '',
    status: row.status || 'active',
  }
  showEditModal.value = true
}

async function handleSave() {
  await editFormRef.value?.validate()
  saving.value = true
  try {
    if (editId.value) {
      await api.update({ proxy_id: editId.value, ...editForm.value })
      message.success('更新成功')
    }
    else {
      await api.create(editForm.value)
      message.success('创建成功')
    }
    showEditModal.value = false
    $table.value?.handleSearch()
  }
  catch (error) {
    console.error('保存失败：', error)
  }
  finally {
    saving.value = false
  }
}

async function handleDelete(row) {
  window.$dialog.warning({
    title: '确认删除',
    content: `确定要删除代理 ${row.proxy_host}:${row.proxy_port} 吗？删除后将进入回收站。`,
    positiveText: '确定',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.delete(row.id)
        message.success('删除成功')
        $table.value?.handleSearch()
      }
      catch (error) {
        console.error('删除失败：', error)
      }
    },
  })
}

onMounted(() => {
  $table.value?.handleSearch()
})

onActivated(() => {
  $table.value?.handleSearch()
})
</script>
