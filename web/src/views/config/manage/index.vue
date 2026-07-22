<template>
  <CommonPage title="配置中心">
    <template #action>
      <n-button v-permission="'post/api/v1/config/create'" type="primary" @click="handleAdd">
        <TheIcon icon="material-symbols:add" :size="16" class="mr-5" />
        新增 Provider
      </n-button>
    </template>

    <!-- Provider 管理 -->
    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :get-data="api.getProviders"
      :columns="providerColumns"
      :is-pagination="false"
      :row-props="rowProps"
    >
      <template #queryBar>
        <n-select
          v-model:value="queryItems.provider_type"
          :options="typeOptions"
          placeholder="按类型筛选"
          clearable
          style="width: 160px"
          @update:value="$table?.handleSearch()"
        />
      </template>
    </CrudTable>

    <!-- ConfigItem 编辑面板 -->
    <n-card
      v-if="selectedProvider"
      :title="`配置项 - ${selectedProvider.provider_name}`"
      size="small"
      mt-16
    >
      <template #header-extra>
        <n-space>
          <n-button size="small" @click="loadItems(selectedProvider.id)">
            刷新
          </n-button>
          <n-button size="small" @click="showSecret = !showSecret">
            {{ showSecret ? '隐藏敏感字段' : '显示敏感字段' }}
          </n-button>
          <n-button size="small" :type="editMode === 'json' ? 'primary' : 'default'" @click="toggleEditMode">
            {{ editMode === 'json' ? '表单模式' : 'JSON 模式' }}
          </n-button>
        </n-space>
      </template>

      <!-- JSON 模式 -->
      <div v-if="editMode === 'json'" mb-16>
        <JsonEditor
          v-model="jsonText"
          hint="直接编辑 JSON，点击空白处自动同步到表单"
          @blur="syncJsonToForm"
          @change="syncJsonToForm"
        />
      </div>

      <!-- 表单编辑器 -->
      <n-grid v-if="itemList.length > 0" :cols="2" :x-gap="24" :y-gap="12">
        <n-form-item-gi
          v-for="item in itemList"
          :key="item.id"
          :label="`${item.config_key}${item.description ? ` (${item.description})` : ''}`"
          :label-props="{ style: 'font-weight: 500' }"
        >
          <template v-if="item.remark" #feedback>
            <span style="color: #999">{{ item.remark }}</span>
          </template>

          <n-input-group>
            <n-switch
              v-if="item.config_type === 'bool'"
              :value="item.config_value === 'true' || item.config_value === '1'"
              @update:value="(v) => { item.config_value = v ? 'true' : 'false'; onFormChange() }"
            />
            <n-input-number
              v-else-if="item.config_type === 'int'"
              :value="Number(item.config_value) || 0"
              size="small"
              style="flex: 1"
              @update:value="(v) => { item.config_value = String(v); onFormChange() }"
            />
            <n-input-number
              v-else-if="item.config_type === 'float'"
              :value="Number(item.config_value) || 0"
              :step="0.1"
              size="small"
              style="flex: 1"
              @update:value="(v) => { item.config_value = String(v); onFormChange() }"
            />
            <n-input
              v-else-if="item.is_secret"
              :type="showSecret ? 'text' : 'password'"
              :value="item.config_value"
              show-password-on="click"
              size="small"
              style="flex: 1"
              @update:value="(v) => { item.config_value = v; onFormChange() }"
            />
            <n-input
              v-else
              :value="item.config_value"
              size="small"
              style="flex: 1"
              @update:value="(v) => { item.config_value = v; onFormChange() }"
            />
            <n-tag
              :type="item.config_type === 'token' || item.config_type === 'password' ? 'warning' : 'default'"
              size="small"
              :bordered="false"
            >
              {{ item.config_type }}
            </n-tag>
            <n-button
              size="tiny"
              type="error"
              quaternary
              @click="deleteConfigItem(item)"
            >
              <TheIcon icon="material-symbols:delete-outline" :size="14" />
            </n-button>
          </n-input-group>
        </n-form-item-gi>
      </n-grid>

      <n-empty v-else description="该 Provider 暂无配置项" />

      <div v-if="itemList.length > 0" mt-20 flex justify-center>
        <n-button v-permission="'post/api/v1/config/batch-save'" type="primary" size="large" :loading="saving" @click="saveItems">
          保存配置项
        </n-button>
      </div>
    </n-card>

    <!-- 已绑定账号 -->
    <n-card
      v-if="selectedProvider"
      title="已绑定账号"
      size="small"
      mt-16
    >
      <n-data-table
        v-if="boundAccounts.length > 0"
        :columns="accountColumns"
        :data="boundAccounts"
        :bordered="false"
        :single-line="false"
        size="small"
        max-height="300"
        :pagination="false"
      />
      <n-empty v-else description="暂无账号绑定到此 Provider" size="small" />
    </n-card>

    <!-- 未选择 Provider 时的提示 -->
    <n-card v-else mt-16>
      <n-empty description="点击上方表格中的「配置」按钮，编辑 Provider 的配置项" />
    </n-card>

    <!-- Provider 弹窗 -->
    <CrudModal
      v-model:visible="modalVisible"
      :title="modalTitle"
      :loading="modalLoading"
      @save="handleSave"
    >
      <n-form ref="modalFormRef" :model="modalForm" label-placement="left" :label-width="80">
        <n-form-item label="类型" required>
          <n-select v-model:value="modalForm.provider_type" :options="typeOptions.filter(t => t.value)" />
        </n-form-item>
        <n-form-item label="名称" required>
          <n-input v-model:value="modalForm.provider_name" placeholder="如：Cloudflare 主账号" />
        </n-form-item>
        <n-form-item label="描述">
          <n-input v-model:value="modalForm.description" placeholder="可选" />
        </n-form-item>
        <n-form-item label="备注">
          <n-input v-model:value="modalForm.remark" placeholder="可选" />
        </n-form-item>
        <n-form-item label="状态">
          <n-select v-model:value="modalForm.status" :options="statusOptions" />
        </n-form-item>
        <n-form-item label="优先级">
          <n-input-number v-model:value="modalForm.priority" :min="0" :max="999" />
        </n-form-item>
        <n-form-item label="默认">
          <n-switch v-model:value="modalForm.is_default" />
        </n-form-item>
        <n-form-item label="标签">
          <n-input v-model:value="modalForm.tags" placeholder="逗号分隔" />
        </n-form-item>
      </n-form>
    </CrudModal>
  </CommonPage>
</template>

<script setup>
import { h, ref, reactive, computed, onMounted } from 'vue'
import {
  NButton, NCard, NEmpty, NForm, NFormItem, NFormItemGi, NGrid,
  NInput, NInputGroup, NInputNumber, NSelect, NSpace, NSwitch,
  NTag, useMessage,
} from 'naive-ui'

import CommonPage from '@/components/page/CommonPage.vue'
import CrudTable from '@/components/table/CrudTable.vue'
import CrudModal from '@/components/table/CrudModal.vue'
import TheIcon from '@/components/icon/TheIcon.vue'
import JsonEditor from '@/components/editor/JsonEditor.vue'
import { useCRUD } from '@/composables'
import api from '@/api/configProvider'
import accountsApi from '@/api'

defineOptions({ name: '配置中心' })

const message = useMessage()

// ─── 常量 ───
const statusOptions = [
  { value: 'active', label: '启用' },
  { value: 'disabled', label: '禁用' },
  { value: 'expired', label: '已过期' },
  { value: 'error', label: '异常' },
]

const statusTypeMap = { active: 'success', disabled: 'default', expired: 'warning', error: 'error' }

// ─── Provider CRUD (useCRUD) ───
const $table = ref(null)
const queryItems = reactive({ provider_type: null })
const typeOptions = ref([])

const initForm = {
  provider_type: 'cloudflare',
  provider_name: '',
  description: '',
  remark: '',
  status: 'active',
  priority: 10,
  is_default: false,
  tags: '',
}

const {
  modalVisible,
  modalTitle,
  modalLoading,
  handleAdd,
  handleEdit,
  handleSave,
  modalForm,
  modalFormRef,
} = useCRUD({
  name: 'Provider',
  initForm,
  doCreate: api.createProvider,
  doUpdate: api.updateProvider,
  doDelete: api.deleteProvider,
  refresh: () => $table.value?.handleSearch(),
})

// ─── Provider 表格列 ───
const providerColumns = computed(() => [
  { title: 'ID', key: 'id', width: 50, align: 'center' },
  {
    title: '类型', key: 'provider_type', width: 100,
    render(row) {
      const type = typeOptions.value.find(t => t.value === row.provider_type)
      return h(NTag, { size: 'small', bordered: false }, () => type?.label || row.provider_type)
    },
  },
  { title: '名称', key: 'provider_name', width: 180, ellipsis: { tooltip: true } },
  { title: '描述', key: 'description', width: 150, ellipsis: { tooltip: true } },
  { title: '备注', key: 'remark', width: 120, ellipsis: { tooltip: true } },
  {
    title: '状态', key: 'status', width: 70,
    render(row) {
      return h(NTag, { type: statusTypeMap[row.status] || 'default', size: 'small' }, () => row.status)
    },
  },
  { title: '优先', key: 'priority', width: 60 },
  { title: '配置项', key: 'item_count', width: 70, align: 'center' },
  {
    title: '默认', key: 'is_default', width: 60, align: 'center',
    render(row) {
      return row.is_default ? h(NTag, { type: 'info', size: 'small' }, () => '是') : '-'
    },
  },
  {
    title: '操作', key: 'actions', width: 240,
    render(row) {
      return h(NSpace, { size: 'small' }, () => [
        h(NButton, { size: 'tiny', onClick: () => selectProvider(row) }, () => '配置'),
        h(NButton, { size: 'tiny', secondary: true, onClick: () => toggleStatus(row) },
          () => row.status === 'active' ? '禁用' : '启用',
        ),
        h(NButton, { size: 'tiny', secondary: true, onClick: () => handleEdit(row) }, () => '编辑'),
        row.is_default
          ? h(NTag, { type: 'info', size: 'small' }, () => '默认')
          : h(NButton, { size: 'tiny', secondary: true, onClick: () => setDefault(row.id) }, () => '设默认'),
        h(NButton, { size: 'tiny', type: 'error', quaternary: true, onClick: () => removeProvider(row.id) },
          () => '删除',
        ),
      ])
    },
  },
])

function rowProps(row) {
  return {
    style: 'cursor: pointer',
    onClick: () => selectProvider(row),
  }
}

// ─── Provider 自定义操作 ───
async function toggleStatus(row) {
  const newStatus = row.status === 'active' ? 'disabled' : 'active'
  try {
    await api.updateProvider({ id: row.id, status: newStatus })
    row.status = newStatus
    message.success(`已${newStatus === 'active' ? '启用' : '禁用'}`)
  } catch {
    message.error('操作失败')
  }
}

async function setDefault(id) {
  await api.setDefaultProvider({ id })
  message.success('已设为默认')
  $table.value?.handleSearch()
}

async function removeProvider(id) {
  try {
    await api.deleteProvider({ id })
    if (selectedProvider.value?.id === id) {
      selectedProvider.value = null
      itemList.value = []
    }
    message.success('已移入回收站')
    $table.value?.handleSearch()
  } catch {
    message.error('删除失败')
  }
}

// ─── ConfigItem 编辑 ───
const selectedProvider = ref(null)
const itemList = ref([])
const showSecret = ref(false)
const saving = ref(false)
const editMode = ref('form')
const jsonText = ref('')
const jsonError = ref('')

function selectProvider(row) {
  selectedProvider.value = { ...row }
  editMode.value = 'form'
  jsonError.value = ''
  loadItems(row.id)
  loadBoundAccounts(row.id)
}

async function loadItems(providerId) {
  try {
    const r = await api.getItems({ provider_id: providerId })
    itemList.value = r.data || []
    syncFormToJson()
  } catch {
    itemList.value = []
  }
}

// ─── 已绑定账号 ───
const boundAccounts = ref([])

const accountColumns = [
  { title: '账号类型', key: 'account_type', width: 140 },
  { title: '账号', key: 'username', width: 200, ellipsis: { tooltip: true } },
  {
    title: '密码', key: 'password', width: 140,
    render: (row) => h(NButton, {
      size: 'tiny', quaternary: true,
      onClick: () => { row._revealed = !row._revealed },
    }, { default: () => row._revealed ? row.password : '\u2022\u2022\u2022\u2022\u2022\u2022' }),
  },
  { title: '环境ID', key: 'env_id', width: 140, align: 'center' },
  { title: '备注', key: 'remark', ellipsis: { tooltip: true } },
]

async function loadBoundAccounts(providerId) {
  try {
    const r = await accountsApi.getAccountList({ provider_id: providerId, page_size: 500 })
    boundAccounts.value = r.data || []
  } catch {
    boundAccounts.value = []
  }
}

// ─── JSON ↔ 表单 双向联动 ───
function buildJsonFromItems() {
  const obj = {}
  for (const item of itemList.value) {
    obj[item.config_key] = item.config_value
  }
  return JSON.stringify(obj, null, 2)
}

function syncFormToJson() {
  if (editMode.value === 'json') {
    jsonText.value = buildJsonFromItems()
    jsonError.value = ''
  }
}

function syncJsonToForm() {
  if (editMode.value !== 'json') return
  try {
    const obj = JSON.parse(jsonText.value)
    if (typeof obj !== 'object' || Array.isArray(obj) || obj === null) {
      jsonError.value = '必须是对象格式 {"key": "value", ...}'
      return
    }
    const keyMap = {}
    for (const item of itemList.value) {
      keyMap[item.config_key] = item
    }
    for (const [key, value] of Object.entries(obj)) {
      if (keyMap[key]) {
        keyMap[key].config_value = String(value)
      }
    }
    jsonError.value = ''
  } catch (e) {
    jsonError.value = e.message
  }
}

function toggleEditMode() {
  if (editMode.value === 'form') {
    jsonText.value = buildJsonFromItems()
    jsonError.value = ''
    editMode.value = 'json'
  } else {
    syncJsonToForm()
    editMode.value = 'form'
    jsonError.value = ''
  }
}

function onFormChange() {
  if (editMode.value === 'json') {
    syncFormToJson()
  }
}

async function deleteConfigItem(item) {
  try {
    await api.deleteItem({ id: item.id })
    itemList.value = itemList.value.filter(it => it.id !== item.id)
    if (editMode.value === 'json') {
      syncFormToJson()
    }
    message.success('已删除')
  } catch {
    message.error('删除失败')
  }
}

async function saveItems() {
  saving.value = true
  try {
    if (editMode.value === 'json') {
      syncJsonToForm()
      if (jsonError.value) {
        message.error('请先修复 JSON 格式错误')
        saving.value = false
        return
      }
    }
    await api.batchSaveItems({
      provider_id: selectedProvider.value.id,
      items: itemList.value.map(it => ({
        provider_id: selectedProvider.value.id,
        config_key: it.config_key,
        config_value: it.config_value,
        config_type: it.config_type,
        is_secret: it.is_secret,
        is_required: it.is_required,
        description: it.description || '',
        remark: it.remark || '',
        sort: it.sort || 0,
      })),
    })
    message.success('保存成功')
    await loadItems(selectedProvider.value.id)  // 重新加载以获取新建项的真实 ID
  } catch {
    message.error('保存失败')
  }
  saving.value = false
}

// ─── 初始化 ───
onMounted(async () => {
  const r = await api.getProviderTypes()
  typeOptions.value = (r.data || []).map(t => ({ value: t.value, label: t.label }))
  $table.value?.handleSearch()
})
</script>
