<template>
  <div class="hub-job-page">
    <n-h3 prefix="bar">HubStudio 任务管理</n-h3>

    <!-- Agent 状态栏 -->
    <n-card size="small" style="margin-bottom: 12px">
      <n-space align="center">
        <span style="font-weight: bold">Agent 状态：</span>
        <template v-if="agents.length === 0">
          <n-tag type="warning" round>
            <template #icon><n-icon><component :is="warningIcon" /></n-icon></template>
            无 Agent 在线
          </n-tag>
          <n-text depth="3">任务将进入 pending 队列等待，或使用</n-text>
          <n-tag type="info" size="small">同步执行</n-tag>
          <n-text depth="3">降级模式</n-text>
        </template>
        <template v-else>
          <n-tag v-for="agent in agents" :key="agent.worker_name" :type="agent.online ? 'success' : 'default'" round size="small">
            {{ agent.worker_name }} {{ agent.online ? '在线' : '离线' }}
          </n-tag>
          <n-text depth="3">{{ pendingJobs }} 个待执行</n-text>
        </template>
        <n-button text size="tiny" @click="loadAgentStatus">刷新</n-button>
      </n-space>
    </n-card>

    <CrudTable
      ref="crudRef"
      :columns="columns"
      :query-items="queryItems"
      :get-data="getData"
      :page-size="20"
      @onChecked="onCheckedChange"
      @update:query-items="onUpdateQueryItems"
    >
      <template #queryBar>
        <n-select
          v-model:value="queryItems.job_type"
          :options="jobTypeOptions"
          placeholder="任务类型"
          clearable
          style="width: 150px"
        />
        <n-select
          v-model:value="queryItems.status"
          :options="statusOptions"
          placeholder="状态"
          clearable
          style="width: 130px"
        />
        <n-input
          v-model:value="queryItems.domain"
          placeholder="域名搜索"
          clearable
          style="width: 200px"
          @keyup.enter="crudRef.handleQuery()"
        />
      </template>
      <template #queryBarActions>
        <n-button type="warning" size="small" ghost @click="batchRetry">
          批量重试
        </n-button>
        <n-button
          type="error"
          size="small"
          ghost
          :disabled="canBatchCancel.length === 0"
          @click="batchCancel"
        >
          批量取消 ({{ canBatchCancel.length }})
        </n-button>
      </template>
    </CrudTable>

    <!-- 任务详情弹窗 -->
    <n-modal v-model:show="showDetail" title="任务详情" preset="dialog">
      <n-descriptions v-if="detail" :column="2" bordered size="small">
        <n-descriptions-item label="任务 ID">{{ detail.id }}</n-descriptions-item>
        <n-descriptions-item label="域名">{{ detail.domain }}</n-descriptions-item>
        <n-descriptions-item label="任务类型">{{ detail.job_type }}</n-descriptions-item>
        <n-descriptions-item label="状态">
          <n-tag :type="statusTypeMap[detail.status]">{{ detail.status }}</n-tag>
        </n-descriptions-item>
        <n-descriptions-item label="执行节点">{{ detail.worker_name || '-' }}</n-descriptions-item>
        <n-descriptions-item label="重试次数">{{ detail.retry_count || 0 }}</n-descriptions-item>
        <n-descriptions-item label="Provider ID">{{ detail.provider_id || 0 }}</n-descriptions-item>
        <n-descriptions-item label="站点 ID">{{ detail.site_id }}</n-descriptions-item>
        <n-descriptions-item label="开始时间" :span="2">{{ detail.started_at || '-' }}</n-descriptions-item>
        <n-descriptions-item label="完成时间" :span="2">{{ detail.finished_at || '-' }}</n-descriptions-item>
        <n-descriptions-item label="错误信息" :span="2">
          <pre v-if="detail.error_message" style="max-height: 200px; overflow: auto; font-size: 12px; color: #d03050">{{ detail.error_message }}</pre>
          <span v-else>-</span>
        </n-descriptions-item>
      </n-descriptions>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, h, computed } from 'vue'
import {
  NButton, NCard, NDescriptions, NDescriptionsItem,
  NH3, NIcon, NInput, NModal, NSelect, NSpace,
  NTag, NText, useMessage,
} from 'naive-ui'
import { WarnFilled } from '@vicons/carbon'
import CrudTable from '@/components/table/CrudTable.vue'
import API from '~/src/api/site-pipeline'

const message = useMessage()
const warningIcon = WarnFilled
const crudRef = ref(null)

// ─── 查询参数 ───
const queryItems = reactive({
  job_type: '',
  status: '',
  domain: '',
})

function onUpdateQueryItems(val) {
  Object.assign(queryItems, val)
}

// ─── 选中项 ───
const checkedRowKeysRef = ref([])
function onCheckedChange(keys) {
  checkedRowKeysRef.value = keys
}

const canBatchCancel = computed(() => {
  const data = crudRef.value?.tableData || []
  return data.filter(r => (r.status === 'pending' || r.status === 'running') && checkedRowKeysRef.value.includes(r.id))
})

// ─── 详情弹窗 ───
const showDetail = ref(false)
const detail = ref(null)

// ─── Agent 状态 ───
const agents = ref([])
const pendingJobs = ref(0)

// ─── 数据加载 ───
async function getData({ page, page_size, job_type, status, domain }) {
  const params = { page, page_size }
  if (job_type) params.job_type = job_type
  if (status) params.status = status
  if (domain) params.domain = domain
  const r = await API.getHubJobList(params)
  return { data: r.data || [], total: r.total || 0 }
}

onMounted(() => {
  loadAgentStatus()
})

async function loadAgentStatus() {
  try {
    const r = await API.getAgentStatus()
    agents.value = r.data?.agents || []
    pendingJobs.value = r.data?.pending_jobs || 0
  } catch (e) {
    // ignore
  }
}

// ─── 选项 ───
const jobTypeOptions = [
  { value: '', label: '全部' },
  { value: 'create_env', label: '创建环境' },
  { value: 'create_account', label: '创建账号' },
  { value: 'update_env', label: '更新环境' },
  { value: 'website_control', label: '网站控制' },
  { value: 'gmc_check', label: 'GMC检查' },
]

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待执行' },
  { value: 'running', label: '执行中' },
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
]

const statusTypeMap = {
  pending: 'default',
  running: 'info',
  success: 'success',
  failed: 'error',
}

// ─── 列定义 ───
const columns = [
  {
    type: 'selection',
    width: 40,
  },
  { title: '序号', key: 'index', width: 40, align: 'center', render: (_, index) => index + 1 },
  { title: '域名', key: 'domain', ellipsis: { tooltip: true }, width: 180 },
  { title: '类型', key: 'job_type', width: 90 },
  {
    title: '状态', key: 'status', width: 80,
    render(r) { return h(NTag, { type: statusTypeMap[r.status] || 'default', size: 'small' }, r.status) },
  },
  { title: '节点', key: 'worker_name', width: 100, render(r) { return r.worker_name || '-' } },
  { title: '重试', key: 'retry_count', width: 50 },
  {
    title: '操作', key: 'actions', width: 180,
    render(r) {
      const btns = []
      btns.push(h(NButton, { size: 'small', quaternary: true, onClick: () => { detail.value = r; showDetail.value = true } }, '详情'))
      if (r.status === 'failed' || r.status === 'pending') {
        btns.push(h(NButton, { size: 'small', quaternary: true, type: 'warning', onClick: () => retryJob(r.id, false) }, '重试'))
      }
      if (r.status === 'pending' && agents.value.filter(a => a.online).length === 0) {
        btns.push(h(NButton, { size: 'small', quaternary: true, type: 'info', onClick: () => retryJob(r.id, true) }, '同步执行'))
      }
      if (r.status === 'pending' || r.status === 'running') {
        btns.push(h(NButton, { size: 'small', quaternary: true, type: 'error', onClick: () => cancelJob(r.id) }, '取消'))
      }
      return h(NSpace, { size: 4 }, btns)
    },
  },
  { title: '开始时间', key: 'started_at', width: 140, render(r) { return r.started_at || '-' } },
  { title: '完成时间', key: 'finished_at', width: 140, render(r) { return r.finished_at || '-' } },
  { title: '创建时间', key: 'created_at', width: 140 },
]

// ─── 操作函数 ───
async function retryJob(jobId, executeNow) {
  try {
    await API.retryHubJob(jobId, executeNow)
    message.success(executeNow ? '已同步重试执行' : '已重置为待执行')
    crudRef.value.handleQuery()
    loadAgentStatus()
  } catch (e) {
    message.error(`重试失败: ${e}`)
  }
}

async function batchRetry() {
  const selected = (crudRef.value?.tableData || []).filter(r => r.status === 'failed' && checkedRowKeysRef.value.includes(r.id))
  if (selected.length === 0) {
    message.warning('请选择 failed 状态的任务')
    return
  }
  for (const r of selected) {
    try { await API.retryHubJob(r.id) } catch (e) { /* continue */ }
  }
  message.success(`已重置 ${selected.length} 个任务为 pending`)
  crudRef.value.handleQuery()
  loadAgentStatus()
}

async function cancelJob(jobId) {
  try {
    await API.cancelHubJob(jobId)
    message.success('任务已取消')
    crudRef.value.handleQuery()
    loadAgentStatus()
  } catch (e) {
    message.error(`取消失败: ${e}`)
  }
}

async function batchCancel() {
  if (canBatchCancel.value.length === 0) {
    message.warning('请选择 pending 或 running 状态的任务')
    return
  }
  try {
    const ids = canBatchCancel.value.map(r => r.id)
    const r = await API.batchCancelHubJobs(ids)
    message.success(`批量取消完成: 成功 ${r.data?.success || ids.length}`)
    checkedRowKeysRef.value = []
    crudRef.value.handleQuery()
    loadAgentStatus()
  } catch (e) {
    message.error(`批量取消失败: ${e}`)
  }
}
</script>

<style scoped>
.hub-job-page { padding: 16px; }
</style>
