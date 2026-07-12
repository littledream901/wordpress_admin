<template>
  <CommonPage title="资源绑定">
    <!-- 顶部筛选 -->
    <n-space mb-15 align="center">
      <span>站点：</span>
      <n-select
        v-model:value="filterSiteId"
        :options="siteOptions"
        :loading="loading"
        placeholder="全部站点"
        clearable
        filterable
        style="width: 280px"
        @update:value="onFilter"
      />
      <n-button type="primary" size="small" @click="loadAll">
        刷新
      </n-button>
      <n-button type="info" size="small" :disabled="checkedSiteIds.length === 0" @click="openBatchModal">
        批量绑定 ({{ checkedSiteIds.length }})
      </n-button>
      <n-tag type="info" size="small" :bordered="false">
        默认 Provider 标记为灰色，(默认) 前缀
      </n-tag>
    </n-space>

    <!-- 域名 ↔ Provider 映射表 -->
    <n-empty v-if="rows.length === 0 && !loading" description="暂无可展示的站点">
      <template #extra>
        <n-text depth="3">请先在「站点管理」中创建站点，再在此处绑定 Provider</n-text>
      </template>
    </n-empty>

    <n-data-table
      v-else
      :columns="tableColumns"
      :data="rows"
      :bordered="false"
      :single-line="false"
      size="small"
      :loading="loading"
      :row-key="getRowKey"
      :checked-row-keys="checkedSiteIds"
      @update:checked-row-keys="checkedSiteIds = $event"
    />

    <!-- 绑定弹窗 -->
    <n-modal v-model:show="showModal" preset="dialog" title="绑定 Provider"
      positive-text="确认绑定" :positive-button-props="{ type: 'primary', loading: submitting }"
      negative-text="取消"
      @positive-click="handleBind"
      @negative-click="showModal = false"
    >
      <n-form label-placement="left" :label-width="100">
        <n-form-item label="站点">
          <n-text>{{ currentSiteName }}</n-text>
        </n-form-item>
        <n-form-item label="Provider 类型">
          <n-text>{{ typeOptions.find(t => t.value === bindForm.provider_type)?.label || bindForm.provider_type }}</n-text>
        </n-form-item>
        <n-form-item label="Provider" required>
          <n-select
            v-model:value="bindForm.provider_id"
            :options="currentTypeProviders"
            placeholder="选择 Provider"
            filterable
          />
        </n-form-item>
      </n-form>
    </n-modal>

    <!-- 批量绑定弹窗 -->
    <n-modal v-model:show="showBatchModal" preset="dialog" title="批量绑定 Provider"
      positive-text="确认绑定" :positive-button-props="{ type: 'primary', loading: batchSubmitting }"
      negative-text="取消"
      @positive-click="handleBatchBind"
      style="width: 540px"
    >
      <n-space vertical size="small">
        <n-tag type="info" size="small">
          已选 {{ checkedSiteIds.length }} 个站点
        </n-tag>

        <div style="display:grid; grid-template-columns:36px 180px 180px 56px; gap:12px; align-items:center;">
          <!-- 表头 -->
          <div style="text-align:center; font-size:13px; font-weight:500; color:#666;">序号</div>
          <div style="font-size:13px; font-weight:500; color:#666;">类型</div>
          <div style="font-size:13px; font-weight:500; color:#666;">Provider</div>
          <div style="text-align:center; font-size:13px; font-weight:500; color:#666;">操作</div>

          <!-- 数据行 -->
          <template v-for="(row, index) in batchRows" :key="index">
            <div style="text-align:center; color:#999; font-size:13px;">{{ index + 1 }}</div>
            <n-select
              v-model:value="row.provider_type"
              :options="typeOptions"
              placeholder="选择类型"
              @update:value="onBatchRowTypeChange(index)"
            />
            <n-select
              v-model:value="row.provider_id"
              :options="getBatchRowProviderOptions(row.provider_type)"
              placeholder="选择 Provider"
              filterable
            />
            <div style="display:flex; justify-content:center;">
              <n-button size="small" type="error" quaternary @click="removeBatchRow(index)" :disabled="batchRows.length <= 1">
                删除
              </n-button>
            </div>
          </template>
        </div>

        <n-button dashed size="small" block @click="addBatchRow">
          + 新增类型
        </n-button>
      </n-space>
    </n-modal>
  </CommonPage>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { NButton, NDataTable, NEmpty, NForm, NFormItem, NModal, NSelect, NSpace, NTag, NText, useMessage } from 'naive-ui'
import CommonPage from '@/components/page/CommonPage.vue'
import ProviderAPI from '@/api/configProvider'
import SiteAPI from '@/api/site-pipeline'

const message = useMessage()
const loading = ref(false)
const filterSiteId = ref(null)

// 核心 provider 类型（按业务顺序）
const CORE_TYPES = ['cloudflare', 'dynadot', 'onepanel', 'hubstudio']
const typeTypeMap = { cloudflare: 'info', dynadot: 'warning', onepanel: 'success', hubstudio: 'default' }

const typeOptions = ref([])
const allProviders = ref([])   // 所有 provider 实例
const allBindings = ref([])    // 所有绑定
const siteOptions = ref([])    // 站点列表
const rows = ref([])           // 表格行

// 默认 provider 按类型索引
const defaultProviderMap = computed(() => {
  const map = {}
  for (const p of allProviders.value) {
    if (p.is_default && CORE_TYPES.includes(p.provider_type)) {
      map[p.provider_type] = p
    }
  }
  return map
})

// 绑定关系索引: "siteId:providerType" → binding
const bindingMap = computed(() => {
  const map = {}
  for (const b of allBindings.value) {
    if (CORE_TYPES.includes(b.provider_type)) {
      const pid = typeof b.provider_id === 'number' ? b.provider_id : (b.provider ?? 0)
      const key = `${b.resource_id}:${b.provider_type}`
      map[key] = { ...b, _provider_id: pid }
    }
  }
  return map
})

// 构建表格行
function buildRows() {
  const result = []
  const sites = filterSiteId.value
    ? siteOptions.value.filter(s => s.value === filterSiteId.value)
    : siteOptions.value

  for (const site of sites) {
    const row = {
      _siteId: site.value,
      siteLabel: site.label,
      cells: {},
    }
    for (const ptype of CORE_TYPES) {
      const key = `${site.value}:${ptype}`
      const binding = bindingMap.value[key]
      if (binding) {
        const p = allProviders.value.find(p => p.id === binding._provider_id)
        row.cells[ptype] = {
          bound: true,
          bindingId: binding.id,
          providerId: binding._provider_id,
          providerName: p?.provider_name || `Provider #${binding._provider_id}`,
          isDefault: p?.is_default || false,
        }
      } else {
        const dp = defaultProviderMap.value[ptype]
        row.cells[ptype] = {
          bound: false,
          providerName: dp?.provider_name || '无默认',
          providerId: dp?.id || null,
          isDefault: true,
        }
      }
    }
    result.push(row)
  }
  rows.value = result
}

// 动态表格列
const tableColumns = computed(() => {
  const cols = [
    { type: 'selection' },
    { title: '站点', key: 'site', width: 200,
      render(row) { return row.siteLabel },
    },
  ]
  for (const ptype of CORE_TYPES) {
    const label = typeOptions.value.find(t => t.value === ptype)?.label || ptype
    cols.push({
      title: label, key: ptype, width: 200,
      render(row) {
        const cell = row.cells[ptype]
        if (!cell) return '-'
        const tags = []
        tags.push(h(NTag, {
          size: 'small',
          type: cell.isDefault ? '' : (typeTypeMap[ptype] || 'default'),
          bordered: false,
          style: cell.isDefault ? 'opacity: 0.6' : '',
        }, () => cell.isDefault ? `(默认) ${cell.providerName}` : cell.providerName))
        tags.push(h('span', { style: 'margin-left: 6px' }, [
          cell.bound
            ? h(NButton, { size: 'tiny', type: 'error', quaternary: true,
                onClick: () => unbind(cell.bindingId),
              }, () => '删除')
            : h(NButton, { size: 'tiny', type: 'primary', quaternary: true,
                onClick: () => openBindModal(row._siteId, ptype, row.siteLabel),
              }, () => '绑定'),
        ]))
        return h(NSpace, { size: 'small', align: 'center' }, () => tags)
      },
    })
  }
  return cols
})

// 弹窗
const showModal = ref(false)
const submitting = ref(false)
const currentSiteName = ref('')
const bindForm = reactive({
  resource_type: 'site',
  resource_id: null,
  provider_type: '',
  provider_id: null,
  bind_type: 'exclusive',
  remark: '',
})

const currentTypeProviders = computed(() => {
  if (!bindForm.provider_type) return []
  return allProviders.value
    .filter(p => p.provider_type === bindForm.provider_type)
    .map(p => ({ value: p.id, label: p.provider_name + (p.is_default ? ' (默认)' : '') }))
})

function openBindModal(siteId, ptype, siteName) {
  Object.assign(bindForm, {
    resource_type: 'site',
    resource_id: siteId,
    provider_type: ptype,
    provider_id: null,
    bind_type: 'exclusive',
    remark: '',
  })
  currentSiteName.value = siteName
  showModal.value = true
}

async function handleBind() {
  if (!bindForm.provider_id) {
    message.warning('请选择 Provider')
    return
  }
  submitting.value = true
  try {
    await ProviderAPI.createBinding({ ...bindForm })
    message.success('绑定成功')
    showModal.value = false
    await loadAll()
  } catch { message.error('绑定失败') }
  submitting.value = false
}

async function unbind(id) {
  await ProviderAPI.deleteBinding({ id })
  message.success('已删除')
  await loadAll()
}

function onFilter() {
  buildRows()
}

async function loadAll() {
  loading.value = true
  try {
    const [sitesR, typesR, providersR, bindingsR] = await Promise.all([
      SiteAPI.getSiteList({ page: 1, pageSize: 1000 }),
      ProviderAPI.getProviderTypes(),
      ProviderAPI.getProviders({}),
      ProviderAPI.getBindings({}),
    ])
    const items = sitesR.data?.items || sitesR.data || []
    siteOptions.value = items.map(s => ({ value: s.id, label: `${s.domain || '未命名'} (ID:${s.id})` }))
    typeOptions.value = (typesR.data || []).map(t => ({ value: t.value, label: t.label }))
    allProviders.value = providersR.data || []
    allBindings.value = bindingsR.data || []
    buildRows()
  } catch (e) {
    console.error(e)
  }
  loading.value = false
}

onMounted(loadAll)

function getRowKey(row) {
  return row._siteId
}

// ── 批量绑定 ──
const checkedSiteIds = ref([])
const showBatchModal = ref(false)
const batchSubmitting = ref(false)
const batchRows = ref([{ provider_type: null, provider_id: null }])

function getBatchRowProviderOptions(providerType) {
  if (!providerType) return []
  return allProviders.value
    .filter(p => p.provider_type === providerType)
    .map(p => ({ value: p.id, label: p.provider_name + (p.is_default ? ' (默认)' : '') }))
}

function onBatchRowTypeChange(index) {
  batchRows.value[index].provider_id = null
}

function addBatchRow() {
  batchRows.value.push({ provider_type: null, provider_id: null })
}

function removeBatchRow(index) {
  if (batchRows.value.length > 1) {
    batchRows.value.splice(index, 1)
  }
}

function openBatchModal() {
  if (checkedSiteIds.value.length === 0) { message.warning('请先勾选站点行'); return }
  batchRows.value = [{ provider_type: null, provider_id: null }]
  showBatchModal.value = true
}

async function handleBatchBind() {
  // 收集有效的绑定行
  const validRows = batchRows.value.filter(r => r.provider_type && r.provider_id)
  if (validRows.length === 0) { message.warning('请至少完成一行类型和 Provider 的选择'); return }

  // 按 provider_type 分组，每组收集 provider_ids
  const typeGroups = {}
  for (const row of validRows) {
    if (!typeGroups[row.provider_type]) typeGroups[row.provider_type] = []
    if (!typeGroups[row.provider_type].includes(row.provider_id)) {
      typeGroups[row.provider_type].push(row.provider_id)
    }
  }

  batchSubmitting.value = true
  let totalSuccess = 0
  let totalFail = 0
  try {
    for (const [ptype, pids] of Object.entries(typeGroups)) {
      try {
        const res = await ProviderAPI.batchCreateBindings({
          site_ids: checkedSiteIds.value,
          provider_type: ptype,
          provider_ids: pids,
          bind_type: 'preferred',
        })
        const result = res.data || res
        totalSuccess += result.success || 0
        totalFail += result.fail || 0
      } catch {
        totalFail += checkedSiteIds.value.length * pids.length
      }
    }
    message.success(`批量绑定完成: 成功 ${totalSuccess} 条, 失败 ${totalFail} 条`)
    showBatchModal.value = false
    checkedSiteIds.value = []
    await loadAll()
  } catch { message.error('批量绑定失败') }
  batchSubmitting.value = false
}
</script>
