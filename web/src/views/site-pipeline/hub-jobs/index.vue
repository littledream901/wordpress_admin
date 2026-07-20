<template>
  <CommonPage show-header title="HubStudio 任务列表">
    <CrudTable
      ref="crudRef"
      :columns="columns"
      :query-items="queryItems"
      :get-data="getData"
      @on-checked="onCheckedChange"
      @update:query-items="onUpdateQueryItems"
    >
      <template #queryBar>
        <n-select
          v-model:value="queryItems.job_type"
          :options="jobTypeOptions"
          placeholder="任务类型"
          clearable
          style="width: 140px"
        />
        <n-select
          v-model:value="queryItems.status"
          :options="statusOptions"
          placeholder="状态"
          clearable
          style="width: 120px"
        />
        <n-input
          v-model:value="queryItems.domain"
          placeholder="域名搜索"
          clearable
          style="width: 200px"
          @keyup.enter="crudRef.handleSearch()"
        />
      </template>
      <template #queryBarActions>
        <template v-if="checkedRowKeys.length">
          <n-divider vertical />
          <span style="white-space: nowrap; font-size: 13px">已选 {{ checkedRowKeys.length }} 项</span>
          <n-button v-permission="'post/api/v1/site-pipeline/hub-job/{job_id}/retry'" size="small" type="warning" ghost @click="batchRetry">
            批量重试
          </n-button>
          <n-button v-permission="'post/api/v1/site-pipeline/hub-job/batch-cancel'"
            size="small"
            type="error"
            ghost
            :disabled="canBatchCancel.length === 0"
            @click="batchCancel"
          >
            批量取消 ({{ canBatchCancel.length }})
          </n-button>
        </template>
      </template>
    </CrudTable>

    <!-- 任务详情弹窗 -->
    <n-modal v-model:show="showDetail" preset="card" title="任务详情" style="width: 900px">
      <n-space vertical>
        <n-descriptions v-if="currentRow" label-placement="left" :column="2" bordered size="small">
          <n-descriptions-item label="ID">{{ currentRow.id }}</n-descriptions-item>
          <n-descriptions-item label="站点ID">{{ currentRow.site_id }}</n-descriptions-item>
          <n-descriptions-item label="域名">{{ currentRow.domain }}</n-descriptions-item>
          <n-descriptions-item label="任务类型">{{ currentRow.job_type }}</n-descriptions-item>
          <n-descriptions-item label="状态">
            <n-tag :type="statusType(currentRow.status)" size="small">{{ currentRow.status }}</n-tag>
          </n-descriptions-item>
          <n-descriptions-item label="Worker">{{ currentRow.worker_name || '-' }}</n-descriptions-item>
          <n-descriptions-item label="开始时间">{{ currentRow.started_at || '-' }}</n-descriptions-item>
          <n-descriptions-item label="完成时间">{{ currentRow.finished_at || '-' }}</n-descriptions-item>
          <n-descriptions-item label="创建时间">{{ currentRow.created_at }}</n-descriptions-item>
          <n-descriptions-item label="更新时间">{{ currentRow.updated_at }}</n-descriptions-item>
        </n-descriptions>
        <n-divider />
        <n-text depth="3">Payload JSON</n-text>
        <n-input type="textarea" :value="currentPayload" :rows="6" readonly />
        <n-text depth="3">Result JSON</n-text>
        <n-input type="textarea" :value="currentResult" :rows="6" readonly />
        <n-text v-if="currentRow?.error_message" depth="3">错误信息</n-text>
        <n-input v-if="currentRow?.error_message" type="textarea" :value="currentRow.error_message" :rows="4" readonly />
        <n-space>
          <n-button @click="copyText(JSON.stringify(currentRow, null, 2))">复制全部</n-button>
          <n-button v-permission="'post/api/v1/site-pipeline/hub-job/{job_id}/retry'" type="warning" @click="retryCurrent" :disabled="!currentRow">重试此任务</n-button>
        </n-space>
      </n-space>
    </n-modal>
  </CommonPage>
</template>

<script setup>
import { h, ref, reactive, computed, onMounted, resolveDirective, withDirectives } from 'vue'
import { NButton, NTag, useMessage } from 'naive-ui'
import CrudTable from '@/components/table/CrudTable.vue'
import api from '@/api/site-pipeline'

const vPermission = resolveDirective('permission')

const message = useMessage()
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
const checkedRowKeys = ref([])
function onCheckedChange(keys) {
  checkedRowKeys.value = keys
}

// ─── 数据加载 ───
async function getData({ page, page_size, job_type, status, domain }) {
  const params = { page, page_size }
  if (job_type) params.job_type = job_type
  if (status) params.status = status
  if (domain) params.domain = domain
  const res = await api.getHubJobList(params)
  return { data: res?.data ?? [], total: res?.total ?? 0 }
}

onMounted(() => {
  crudRef.value?.handleSearch()
})

// ─── 选项 ───
const jobTypeOptions = [
  { value: '', label: '全部' },
  { value: 'create_env', label: '创建环境' },
  { value: 'create_account', label: '创建账号' },
  { value: 'update_env', label: '更新环境' },
  { value: 'wp_login', label: '登录WP' },
  { value: 'gmc_check', label: 'GMC检查' },
]
const jobTypeMap = Object.fromEntries(jobTypeOptions.map(o => [o.value, o.label]))
function jobTypeLabel(v) { return jobTypeMap[v] || v }

const statusOptions = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: '等待中' },
  { value: 'running', label: '执行中' },
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
]

// ─── 详情弹窗 ───
const showDetail = ref(false)
const currentRow = ref(null)
const currentPayload = ref('')
const currentResult = ref('')

function openDetail(row) {
  currentRow.value = row
  try { currentPayload.value = JSON.stringify(JSON.parse(row.payload_json || '{}'), null, 2) } catch { currentPayload.value = row.payload_json || '' }
  try { currentResult.value = JSON.stringify(JSON.parse(row.result_json || '{}'), null, 2) } catch { currentResult.value = row.result_json || '' }
  showDetail.value = true
}

function copyText(text) {
  navigator.clipboard.writeText(text || '')
  message.success('已复制')
}

// ─── 单条操作 ───
async function retryJob(row) {
  await api.dispatchHubJob(row.site_id, { job_type: row.job_type, execute_now: true })
  message.success('已重新触发任务')
  crudRef.value.handleSearch()
}

async function retryCurrent() {
  if (!currentRow.value) return
  await retryJob(currentRow.value)
}

async function cancelJob(row) {
  try {
    await api.cancelHubJob(row.id)
    message.success('任务已取消')
    crudRef.value.handleSearch()
  } catch (e) {
    message.error(`取消失败: ${e}`)
  }
}

// ─── 批量操作 ───
async function batchRetry() {
  const selected = (crudRef.value?.tableData || []).filter(
    r => r.status === 'failed' && checkedRowKeys.value.includes(r.id)
  )
  if (!selected.length) {
    message.warning('请选择 failed 状态的任务')
    return
  }
  for (const r of selected) {
    try { await api.retryHubJob(r.id) } catch (e) { /* continue */ }
  }
  message.success(`已重置 ${selected.length} 个任务为 pending`)
  checkedRowKeys.value = []
  crudRef.value.handleSearch()
}

async function batchCancel() {
  const ids = checkedRowKeys.value
  if (!ids.length) {
    message.warning('请选择任务')
    return
  }
  try {
    const r = await api.batchCancelHubJobs(ids)
    message.success(`批量取消完成: 成功 ${r?.data?.success ?? ids.length}`)
    checkedRowKeys.value = []
    crudRef.value.handleSearch()
  } catch (e) {
    message.error(`批量取消失败: ${e}`)
  }
}

// ─── 列定义 ───
const statusType = (s) => {
  if (s === 'success') return 'success'
  if (s === 'failed') return 'error'
  if (s === 'running') return 'info'
  return 'default'
}

const columns = [
  { type: 'selection', width: 40 },
  { title: '序号', key: 'index', width: 50, align: 'center', render: (_, index) => index + 1 },
  { title: '域名', key: 'domain', width: 180, ellipsis: { tooltip: true } },
  { title: '类型', key: 'job_type', width: 100, render: row => jobTypeLabel(row.job_type) },
  {
    title: '状态', key: 'status', width: 80,
    render: row => h(NTag, { type: statusType(row.status), size: 'small' }, { default: () => row.status }),
  },
  { title: '重试', key: 'retry_count', width: 50 },
  { title: '开始时间', key: 'started_at', width: 150, render: row => row.started_at || '-' },
  { title: '完成时间', key: 'finished_at', width: 150, render: row => row.finished_at || '-' },
  { title: '创建时间', key: 'created_at', width: 150 },
  {
    title: '操作', key: 'actions', width: 180,
    render: row => h('div', { style: 'display:flex;gap:4px;flex-wrap:wrap' }, [
      h(NButton, { size: 'tiny', onClick: () => openDetail(row) }, { default: () => '详情' }),
      withDirectives(h(NButton, { size: 'tiny', type: 'warning', onClick: () => retryJob(row) }, { default: () => '重试' }), [[vPermission, 'post/api/v1/site-pipeline/hub-job/{job_id}/retry']]),
      (row.status === 'pending' || row.status === 'running')
        ? withDirectives(h(NButton, { size: 'tiny', type: 'error', onClick: () => cancelJob(row) }, { default: () => '取消' }), [[vPermission, 'post/api/v1/site-pipeline/hub-job/{job_id}/cancel']])
        : null,
    ].filter(Boolean)),
  },
]
</script>
