<template>
  <CommonPage show-header title="Hub 任务分发">
    <template #action>
      <n-space>
        <n-tag v-if="agentOnline" type="success" round size="small">Agent 在线</n-tag>
        <n-tag v-else type="warning" round size="small">Agent 离线</n-tag>
        <n-button text size="tiny" @click="loadAgentStatus">刷新</n-button>
      </n-space>
    </template>

    <n-space vertical :size="12">
      <!-- 搜索 & 批量操作 -->
      <n-card size="small" rounded-10>
        <n-space align="center" :wrap="false">
          <n-input v-model:value="searchDomain" placeholder="域名搜索" clearable style="width: 200px" @keyup.enter="doSearch" />
          <n-select v-model:value="searchHubStatus" :options="hubStatusFilterOptions" placeholder="Hub状态" clearable style="width: 140px" @update:value="doSearch" />
          <n-button type="primary" @click="doSearch">搜索</n-button>
          <template v-if="checkedRowKeys.length">
            <n-divider vertical />
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
        </n-space>
      </n-card>

      <!-- 站点列表 -->
      <n-data-table
        ref="$table"
        :columns="columns"
        :data="tableData"
        :loading="loading"
        :pagination="pagination"
        :row-key="(r) => r.id"
        size="small"
        @update:checked-row-keys="(keys) => checkedRowKeys = keys"
        @update:page="onPageChange"
        @update:page-size="onPageSizeChange"
      />

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
    </n-space>
  </CommonPage>
</template>

<script setup>
import { h, ref, reactive, onMounted } from 'vue'
import { NButton, NCard, NDataTable, NDivider, NInput, NModal, NSelect, NSpace, NSwitch, NTag, NText, useMessage } from 'naive-ui'
import api from '@/api/site-pipeline'

const message = useMessage()
const loading = ref(false)
const batchLoading = ref(false)
const searchDomain = ref('')
const searchHubStatus = ref('')
const checkedRowKeys = ref([])
const tableData = ref([])
const showDispatch = ref(false)
const dispatchTarget = ref(null)
const dispatchJobType = ref('create_env')
const dispatchExecuteNow = ref(false)
const batchExecuteNow = ref(false)
const batchJobType = ref('create_env')
const agentOnline = ref(false)

const pagination = reactive({ page: 1, pageSize: 20, itemCount: 0, showSizePicker: true, pageSizes: [10, 20, 50, 100] })

const hubStatusFilterOptions = [
  { label: '全部', value: '' },
  { label: '未创建', value: '未创建' },
  { label: '已创建', value: '已创建' },
  { label: '创建失败', value: '创建失败' },
]

const batchJobTypeOptions = [
  { label: '创建环境', value: 'create_env' },
  { label: '创建账号', value: 'create_account' },
  { label: '更新环境', value: 'update_env' },
  { label: '网站控制', value: 'website_control' },
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
  { title: '序号', key: 'index', width: 40, align: 'center', render: (_, index) => index + 1 },
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
        { label: '网站控制', type: 'success', action: 'website_control', ghost: !r.hub_env_id },
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

onMounted(() => {
  loadSites()
  loadAgentStatus()
})

async function loadSites() {
  loading.value = true
  try {
    const params = {
      page: pagination.page,
      page_size: pagination.pageSize,
    }
    if (searchDomain.value) params.domain = searchDomain.value
    if (searchHubStatus.value) {
      if (searchHubStatus.value === '未创建') params.hub_status = ''
      else params.hub_status = searchHubStatus.value
    }
    const res = await api.getSiteList(params)
    tableData.value = res.data || []
    pagination.itemCount = res.total || 0
  } catch (e) {
    message.error('加载站点列表失败')
  } finally {
    loading.value = false
  }
}

async function loadAgentStatus() {
  try {
    const r = await api.getAgentStatus()
    agentOnline.value = r.data?.any_online || false
  } catch (_) {}
}

function doSearch() {
  pagination.page = 1
  loadSites()
}

function onPageChange(page) {
  pagination.page = page
  loadSites()
}

function onPageSizeChange(size) {
  pagination.pageSize = size
  pagination.page = 1
  loadSites()
}

function dispatchSingle(row, jobType) {
  dispatchTarget.value = row
  dispatchJobType.value = jobType
  dispatchExecuteNow.value = !agentOnline.value  // Agent 离线默认同步执行
  showDispatch.value = true
}

async function confirmDispatch() {
  const row = dispatchTarget.value
  try {
    const fnMap = {
      create_env: api.triggerHubEnv,
      create_account: api.triggerHubAccount,
      update_env: api.triggerHubUpdate,
      website_control: api.triggerHubControl,
      gmc_check: api.triggerHubGmcCheck,
    }
    const fn = fnMap[dispatchJobType.value]
    if (fn) {
      await fn(row.id, 0, dispatchExecuteNow.value)
      message.success(`站点 ${row.domain} 的 ${dispatchJobType.value} 已派发`)
      showDispatch.value = false
      loadSites()
    }
  } catch (e) {
    message.error(`派发失败: ${e}`)
  }
}

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
      // 同步执行：逐个调用快捷入口
      const fnMap = {
        create_env: api.triggerHubEnv,
        create_account: api.triggerHubAccount,
        update_env: api.triggerHubUpdate,
        website_control: api.triggerHubControl,
        gmc_check: api.triggerHubGmcCheck,
      }
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
      // 异步派发：使用批量接口，由 Agent 领取
      const res = await api.batchHubDispatch(checkedRowKeys.value, batchJobType.value)
      const r = res.data || res
      message.success(`批量派发完成: 成功 ${r.success || 0}, 失败 ${r.fail || 0}`)
    }
    checkedRowKeys.value = []
    loadSites()
  } catch (e) {
    message.error(`批量派发异常: ${e}`)
  } finally {
    batchLoading.value = false
  }
}
</script>
