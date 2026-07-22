<template>
  <CommonPage title="资源绑定">
    <CrudTable
      ref="$table"
      title=""
      :columns="tableColumns"
      :get-data="getBindingSites"
      :query-items="queryItems"
      :show-size-picker="false"
      row-key="id"
      @on-checked="checkedSiteIds = $event"
    >
      <template #queryBar>
        <span>站点：</span>
        <n-select
          v-model:value="queryItems.keyword"
          :options="siteOptions"
          placeholder="全部站点"
          clearable
          filterable
          style="width: 240px"
          @update:value="() => $table?.handleSearch()"
        />
        <span>IP：</span>
        <n-select
          v-model:value="queryItems.server_ip"
          :options="ipOptions"
          placeholder="全部 IP"
          clearable
          filterable
          style="width: 160px"
          @update:value="() => $table?.handleSearch()"
        />
      </template>
      <template #queryBarActions>
        <n-button v-permission="'post/api/v1/config-provider/bindings/batch-create'" type="info" size="small" :disabled="checkedSiteIds.length === 0" @click="openBatchModal">
          批量绑定 ({{ checkedSiteIds.length }})
        </n-button>
        <n-tag type="info" size="small" :bordered="false">
          默认标记为灰色
        </n-tag>
      </template>

    </CrudTable>

    <!-- 绑定弹窗 -->
    <n-modal v-model:show="showModal" preset="dialog" title="绑定 Provider"
      positive-text="确认绑定" :positive-button-props="{ type: 'primary', loading: submitting }"
      negative-text="取消"
      @positive-click="handleBind"
      @negative-click="showModal = false"
    >
      <n-form label-placement="left" :label-width="100">
        <n-form-item label="站点"><n-text>{{ currentSiteName }}</n-text></n-form-item>
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
        <n-tag type="info" size="small">已选 {{ checkedSiteIds.length }} 个站点</n-tag>
        <div style="display:grid; grid-template-columns:36px 180px 180px 56px; gap:12px; align-items:center;">
          <div style="text-align:center; font-size:13px; font-weight:500; color:#666;">序号</div>
          <div style="font-size:13px; font-weight:500; color:#666;">类型</div>
          <div style="font-size:13px; font-weight:500; color:#666;">Provider</div>
          <div style="text-align:center; font-size:13px; font-weight:500; color:#666;">操作</div>
          <template v-for="(row, index) in batchRows" :key="index">
            <div style="text-align:center; color:#999; font-size:13px;">{{ index + 1 }}</div>
            <n-select v-model:value="row.provider_type" :options="typeOptions" placeholder="选择类型" @update:value="onBatchRowTypeChange(index)" />
            <n-select v-model:value="row.provider_id" :options="getBatchRowProviderOptions(row.provider_type)" placeholder="选择 Provider" filterable />
            <div style="display:flex; justify-content:center;">
              <n-button size="small" type="error" quaternary @click="removeBatchRow(index)" :disabled="batchRows.length <= 1">删除</n-button>
            </div>
          </template>
        </div>
        <n-button dashed size="small" block @click="addBatchRow">+ 新增类型</n-button>
      </n-space>
    </n-modal>
  </CommonPage>
</template>

<script setup>
import { ref, reactive, computed, h, onMounted } from 'vue'
import { NButton, NForm, NFormItem, NModal, NSelect, NSpace, NTag, NText, useMessage } from 'naive-ui'
import CommonPage from '@/components/page/CommonPage.vue'
import CrudTable from '@/components/table/CrudTable.vue'
import ProviderAPI from '@/api/configProvider'

const $table = ref(null)
const message = useMessage()

const CORE_TYPES = ['cloudflare', 'dynadot', 'onepanel', 'hubstudio']
const typeTypeMap = { cloudflare: 'info', dynadot: 'warning', onepanel: 'success', hubstudio: 'default' }

const typeOptions = ref([])
const siteOptions = ref([])
const allProviders = ref([])
const ipOptions = ref([])
const checkedSiteIds = ref([])
const queryItems = reactive({ server_ip: null, keyword: null })

// ── CrudTable getData ──
async function getBindingSites({ page, page_size, server_ip, keyword } = {}) {
  const res = await ProviderAPI.getBindingSites({
    page: page || 1,
    page_size: page_size || 10,
    server_ip: server_ip || '',
  })
  const items = Array.isArray(res.data) ? res.data : (res.data?.items || [])
  // 前端站点名模糊筛选
  let data = items
  if (keyword) {
    const kw = keyword.toLowerCase()
    data = items.filter(s => (s.domain || '').toLowerCase().includes(kw))
  }
  return { data, total: res.total || data.length }
}

// ── 表格列 ──
const tableColumns = computed(() => {
  const cols = [
    { type: 'selection', width: 40 },
    {
      title: '站点', key: 'domain', width: 200,
      render(row) { return h('span', row.domain || '未命名') },
    },
    { title: 'IP', key: 'server_ip', width: 140 },
  ]
  for (const ptype of CORE_TYPES) {
    const label = typeOptions.value.find(t => t.value === ptype)?.label || ptype
    cols.push({
      title: label,
      key: `${ptype}_col`,
      width: 200,
      render(row) {
        const b = row.bindings[ptype]
        if (!b) return null
        return h(NSpace, { size: 'small', align: 'center' }, {
          default: () => [
            h(NTag, {
              size: 'small',
              type: b.is_default ? undefined : (typeTypeMap[ptype] || 'default'),
              bordered: false,
              style: b.is_default ? 'opacity:0.6' : '',
            }, { default: () => `${b.is_default ? '(默认) ' : ''}${b.provider_name}` }),
            b.bound
              ? h(NButton, { size: 'tiny', type: 'error', quaternary: true, onClick: () => unbind(b.binding_id) }, { default: () => '删除' })
              : h(NButton, { size: 'tiny', type: 'primary', quaternary: true, onClick: () => openBindModal(row.id, ptype, row.domain) }, { default: () => '绑定' }),
          ],
        })
      },
    })
  }
  return cols
})

// ── 弹窗 ──
const showModal = ref(false)
const submitting = ref(false)
const currentSiteName = ref('')
const bindForm = reactive({ resource_type: 'site', resource_id: null, provider_type: '', provider_id: null, bind_type: 'exclusive', remark: '' })

const currentTypeProviders = computed(() => {
  if (!bindForm.provider_type) return []
  return allProviders.value
    .filter(p => p.provider_type === bindForm.provider_type)
    .map(p => ({ value: p.id, label: p.provider_name + (p.is_default ? ' (默认)' : '') }))
})

function openBindModal(siteId, ptype, domain) {
  Object.assign(bindForm, { resource_id: siteId, provider_type: ptype, provider_id: null, bind_type: 'exclusive', remark: '' })
  currentSiteName.value = domain
  showModal.value = true
}

async function handleBind() {
  if (!bindForm.provider_id) { message.warning('请选择 Provider'); return }
  submitting.value = true
  try {
    await ProviderAPI.createBinding({ ...bindForm })
    message.success('绑定成功')
    showModal.value = false
    $table.value?.handleSearch()
  } catch { message.error('绑定失败') }
  submitting.value = false
}

async function unbind(id) {
  await ProviderAPI.deleteBinding({ id })
  message.success('已删除')
  $table.value?.handleSearch()
}

// ── 初始化 ──
onMounted(async () => {
  const [typesR, providersR, ipsR] = await Promise.all([
    ProviderAPI.getProviderTypes(),
    ProviderAPI.getProviders({}),
    ProviderAPI.getBindingIps(),
  ])
  typeOptions.value = (typesR.data || []).map(t => ({ value: t.value, label: t.label }))
  allProviders.value = providersR.data || []
  ipOptions.value = ipsR.data || []
})

// ── 批量绑定 ──
const showBatchModal = ref(false)
const batchSubmitting = ref(false)
const batchRows = ref([{ provider_type: null, provider_id: null }])

function getBatchRowProviderOptions(providerType) {
  if (!providerType) return []
  return allProviders.value.filter(p => p.provider_type === providerType).map(p => ({ value: p.id, label: p.provider_name + (p.is_default ? ' (默认)' : '') }))
}
function onBatchRowTypeChange(index) { batchRows.value[index].provider_id = null }
function addBatchRow() { batchRows.value.push({ provider_type: null, provider_id: null }) }
function removeBatchRow(index) { if (batchRows.value.length > 1) batchRows.value.splice(index, 1) }
function openBatchModal() {
  if (checkedSiteIds.value.length === 0) { message.warning('请先勾选站点行'); return }
  batchRows.value = [{ provider_type: null, provider_id: null }]
  showBatchModal.value = true
}
async function handleBatchBind() {
  const validRows = batchRows.value.filter(r => r.provider_type && r.provider_id)
  if (validRows.length === 0) { message.warning('请至少完成一行类型和 Provider 的选择'); return }
  const typeGroups = {}
  for (const row of validRows) {
    if (!typeGroups[row.provider_type]) typeGroups[row.provider_type] = []
    if (!typeGroups[row.provider_type].includes(row.provider_id)) typeGroups[row.provider_type].push(row.provider_id)
  }
  batchSubmitting.value = true
  let totalSuccess = 0; let totalFail = 0
  try {
    for (const [ptype, pids] of Object.entries(typeGroups)) {
      try {
        const res = await ProviderAPI.batchCreateBindings({ site_ids: checkedSiteIds.value, provider_type: ptype, provider_ids: pids, bind_type: 'preferred' })
        const result = res.data || res
        totalSuccess += result.success || 0; totalFail += result.fail || 0
      } catch { totalFail += checkedSiteIds.value.length * pids.length }
    }
    message.success(`批量绑定完成: 成功 ${totalSuccess} 条, 失败 ${totalFail} 条`)
    showBatchModal.value = false
    checkedSiteIds.value = []
    $table.value?.handleSearch()
  } catch { message.error('批量绑定失败') }
  batchSubmitting.value = false
}
</script>
