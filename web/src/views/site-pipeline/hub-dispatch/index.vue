<template>
  <CommonPage show-header title="Hub 任务分发">
    <template #action>
      <n-space>
        <n-tag v-if="agentOnline" type="success" round size="small">Agent 在线</n-tag>
        <n-tag v-else type="warning" round size="small">Agent 离线</n-tag>
        <n-button text size="tiny" @click="loadAgentStatus">刷新</n-button>
      </n-space>
    </template>

    <CrudTable
      ref="crudRef"
      :columns="columns"
      :query-items="queryItems"
      :get-data="getData"
      :page-size="20"
      @onChecked="(keys) => checkedRowKeys = keys"
      @update:query-items="onUpdateQueryItems"
    >
      <template #queryBar>
        <n-input
          v-model:value="queryItems.domain"
          placeholder="域名搜索"
          clearable
          style="width: 200px"
          @keyup.enter="crudRef?.handleSearch()"
        />
        <n-select
          v-model:value="queryItems.hub_status"
          :options="hubStatusOptions"
          placeholder="Hub状态"
          clearable
          style="width: 140px"
        />
      </template>
      <template #queryBarActions>
        <template v-if="checkedRowKeys.length">
          <span style="white-space: nowrap; font-size: 13px">已选 {{ checkedRowKeys.length }} 项</span>
          <n-select
            v-model:value="batchJobType"
            :options="batchJobTypeOptions"
            placeholder="任务类型"
            style="width: 120px"
          />
          <n-switch v-model:value="batchExecuteNow" size="small" />
          <n-text depth="3" style="font-size: 12px">同步执行</n-text>
          <n-button type="primary" size="small" :loading="batchLoading" @click="batchDispatch">
            批量派发
          </n-button>
        </template>
      </template>
    </CrudTable>

    <!-- 单站点派发弹窗 -->
    <n-modal v-model:show="showDispatch" preset="card" title="派发 Hub 任务" style="width: 460px">
      <n-space vertical :size="12">
        <n-text>站点: <b>{{ dispatchTarget?.domain }}</b> (ID: {{ dispatchTarget?.id }})</n-text>
        <n-text v-if="dispatchTarget?.hub_env_id" depth="3">已有环境ID: {{ dispatchTarget.hub_env_id }}</n-text>
        <n-select
          v-model:value="dispatchJobType"
          :options="batchJobTypeOptions"
          placeholder="选择任务类型"
        />
        <n-space align="center">
          <n-switch v-model:value="dispatchExecuteNow" />
          <n-text depth="3">同步执行 (Agent 离线时后端直接调用 Connector)</n-text>
        </n-space>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showDispatch = false">取消</n-button>
          <n-button type="primary" @click="confirmDispatch">确认派发</n-button>
        </n-space>
      </template>
    </n-modal>
  </CommonPage>
</template>

<script setup>
import { h, ref, reactive, onMounted } from 'vue'
import { NButton, NModal, NSelect, NSpace, NSwitch, NTag, NText, useMessage } from 'naive-ui'
import CommonPage from '@/components/page/CommonPage.vue'
import CrudTable from '@/components/table/CrudTable.vue'
import api from '@/api/site-pipeline'

const message = useMessage()
const crudRef = ref(null)
const batchLoading = ref(false)
const checkedRowKeys = ref([])
const showDispatch = ref(false)
const dispatchTarget = ref(null)
const dispatchJobType = ref('create_env')
const dispatchExecuteNow = ref(false)
const batchExecuteNow = ref(false)
const batchJobType = ref('create_env')
const agentOnline = ref(false)

const reload = () => crudRef.value?.handleSearch()

const queryItems = reactive({
  domain: '',
  hub_status: '',
})

function onUpdateQueryItems(val) {
  Object.assign(queryItems, val)
}

const hubStatusOptions = [
  { label: '全部', value: '' },
  { label: '未创建', value: '未创建' },
  { label: '已创建', value: '已创建' },
  { label: '创建失败', value: '创建失败' },
]

const batchJobTypeOptions = [
  { label: '创建环境', value: 'create_env' },
  { label: '创建账号', value: 'create_account' },
  { label: '更新环境', value: 'update_env' },
  { label: '登录WP', value: 'website_control' },
  { label: 'GMC检查', value: 'gmc_check' },
]

const statusType = (s) => {
  if (!s) return 'default'
  if (s.includes('success') || s.includes('已创建') || s.includes('exists')) return 'success'
  if (s.includes('failed') || s.includes('失败')) return 'error'
  if (s.includes('running') || s.includes('执行中')) return 'info'
  return 'default'
}

const columns = [
  { type: 'selection', width: 40 },
  { title: '序号', key: 'index', width: 50, align: 'center', render: (_, index) => index + 1 },
  { title: '域名', key: 'domain', width: 200, ellipsis: { tooltip: true } },
  { title: '服务器IP', key: 'server_ip', width: 130 },
  {
    title: 'Hub环境ID', key: 'hub_env_id', width: 130,
    render: (r) => r.hub_env_id || '-',
  },
  {
    title: 'Hub状态', key: 'hub_status', width: 120,
    render: (r) => {
      const label = r.hub_status || '未创建'
      return h(NTag, { type: statusType(r.hub_status), size: 'small' }, label)
    },
  },
  {
    title: '流水线状态', key: 'pipeline_status', width: 120,
    render: (r) => h(NTag, { type: 'default', size: 'small' }, r.pipeline_status || '-'),
  },
  {
    title: 'GMC状态', key: 'gmc_status', width: 100,
    render: (r) => {
      const label = r.gmc_status || '-'
      const typeMap = {
        active: 'success',
        suspended: 'error',
        warning: 'warning',
        pending: 'info',
        query_failed: 'error',
        unknown: 'default',
      }
      return h(NTag, { type: typeMap[r.gmc_status] || 'default', size: 'small' }, label)
    },
  },
  {
    title: '操作', key: 'actions', width: 380, fixed: 'right',
    render: (r) => {
      const buttons = [
        { label: '创建环境', type: 'primary', action: 'create_env', ghost: !r.hub_env_id },
        { label: '创建账号', type: 'info', action: 'create_account', ghost: !r.hub_env_id },
        { label: '更新环境', type: 'warning', action: 'update_env', ghost: !r.hub_env_id },
        { label: '登录WP', type: 'success', action: 'website_control', ghost: !r.hub_env_id },
        { label: 'GMC检查', type: 'tertiary', action: 'gmc_check', ghost: !r.hub_env_id },
      ]
      return h('div', { style: 'display:flex;gap:4px;flex-wrap:wrap' }, buttons.map(btn =>
        h(NButton, {
          size: 'tiny',
          type: btn.type,
          ghost: btn.ghost,
          onClick: () => dispatchSingle(r, btn.action),
        }, btn.label)
      ))
    },
  },
]

// ─── 数据加载 ───

async function getData({ page, page_size, domain, hub_status }) {
  const params = { page, page_size }
  if (domain) params.domain = domain
  if (hub_status) {
    params.hub_status = hub_status === '未创建' ? '' : hub_status
  }
  const res = await api.getSiteList(params)
  return { data: res?.data ?? [], total: res?.total ?? 0 }
}

async function loadAgentStatus() {
  try {
    const r = await api.getAgentStatus()
    agentOnline.value = r.data?.any_online || false
  } catch (_) {}
}

// ─── 生命周期 ───

onMounted(() => {
  crudRef.value?.handleSearch()
  loadAgentStatus()
})

// ─── 单站点派发 ───

function dispatchSingle(row, jobType) {
  dispatchTarget.value = row
  dispatchJobType.value = jobType
  dispatchExecuteNow.value = !agentOnline.value
  showDispatch.value = true
}

const fnMap = {
  create_env: api.triggerHubEnv,
  create_account: api.triggerHubAccount,
  update_env: api.triggerHubUpdate,
  website_control: api.triggerHubControl,
  gmc_check: api.triggerHubGmcCheck,
}

async function confirmDispatch() {
  const row = dispatchTarget.value
  try {
    const fn = fnMap[dispatchJobType.value]
    if (fn) {
      await fn(row.id, 0, dispatchExecuteNow.value)
      message.success(`站点 ${row.domain} 的 ${dispatchJobType.value} 已派发`)
      showDispatch.value = false
      reload()
    }
  } catch (e) {
    message.error(`派发失败: ${e}`)
  }
}

// ─── 批量派发 ───

async function batchDispatch() {
  if (!checkedRowKeys.value.length) {
    message.warning('请先选择站点')
    return
  }
  if (!batchJobType.value) {
    message.warning('请选择任务类型')
    return
  }
  batchLoading.value = true

  try {
    if (batchExecuteNow.value) {
      const fn = fnMap[batchJobType.value]
      let ok = 0, fail = 0
      for (const siteId of checkedRowKeys.value) {
        try {
          await fn(siteId, 0, true)
          ok++
        } catch (_) { fail++ }
      }
      message.success(`批量同步执行完成: 成功 ${ok}, 失败 ${fail}`)
    } else {
      const res = await api.batchHubDispatch(checkedRowKeys.value, batchJobType.value)
      const r = res.data || res
      message.success(`批量派发完成: 成功 ${r.success || 0}, 失败 ${r.fail || 0}`)
    }
    checkedRowKeys.value = []
    reload()
  } catch (e) {
    message.error(`批量派发异常: ${e}`)
  } finally {
    batchLoading.value = false
  }
}
</script>
