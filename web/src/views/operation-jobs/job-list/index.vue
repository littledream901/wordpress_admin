<template>
  <CommonPage show-header title="任务列表">
    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="fetchJobs"
    >
      <template #queryBar>
        <n-select v-model:value="queryItems.action_type" :options="actionOptions" placeholder="操作类型" clearable style="width:160px" />
        <n-select v-model:value="queryItems.status" :options="statusOptions" placeholder="状态" clearable style="width:120px" />
        <n-input v-model:value="queryItems.batch_id" placeholder="批次ID" clearable style="width:160px" @keypress.enter="$table?.handleSearch()" />
      </template>
    </CrudTable>

    <!-- 明细弹窗 -->
    <n-modal v-model:show="showDetail" title="任务详情" preset="dialog" style="width:720px;max-width:90vw">
      <n-spin :show="!detail">
        <template v-if="detail">
          <!-- 基本信息 -->
          <n-descriptions label-placement="left" :column="2" bordered size="small" class="mb16">
            <n-descriptions-item label="ID">{{ detail.id }}</n-descriptions-item>
            <n-descriptions-item label="资源">{{ detail.resource_type }} #{{ detail.resource_id }}</n-descriptions-item>
            <n-descriptions-item label="域名">{{ detail.domain || '-' }}</n-descriptions-item>
            <n-descriptions-item label="操作">{{ detail.action_type }}</n-descriptions-item>
            <n-descriptions-item label="状态"><n-tag :type="statusTag(detail.status)">{{ detail.status }}</n-tag></n-descriptions-item>
            <n-descriptions-item label="步骤">{{ detail.step || '0' }}/{{ detail.total_steps || '1' }}</n-descriptions-item>
            <n-descriptions-item label="批次"><span style="font-size:12px;word-break:break-all">{{ detail.batch_id || '-' }}</span></n-descriptions-item>
            <n-descriptions-item label="节点">{{ detail.worker_name || '-' }}</n-descriptions-item>
            <n-descriptions-item label="账号">{{ providerName }}</n-descriptions-item>
            <n-descriptions-item label="创建时间">{{ detail.created_at }}</n-descriptions-item>
          </n-descriptions>

          <!-- 错误信息 -->
          <div v-if="detail.error_message" class="mb16" style="padding:10px;background:#fff2f0;border:1px solid #ffccc7;border-radius:4px;color:#cf1322;font-size:13px">
            <b>错误：</b>{{ detail.error_message }}
          </div>

          <!-- 结果汇总（批量操作） -->
          <div v-if="resultSummary" class="mb16">
            <div style="font-weight:600;margin-bottom:8px">执行汇总</div>
            <n-space>
              <template v-for="s in resultSummary" :key="s.label">
                <n-tag :type="s.type" size="medium">{{ s.label }}: {{ s.count }}</n-tag>
              </template>
            </n-space>
          </div>

          <!-- 批量结果列表 -->
          <div v-if="resultList.length" class="mb16">
            <div style="font-weight:600;margin-bottom:8px">明细 ({{ resultList.length }})</div>
            <n-data-table
              :columns="resultColumns"
              :data="resultList"
              size="small"
              :max-height="280"
              :bordered="false"
              :single-line="false"
            />
          </div>

          <!-- 原始 JSON（折叠） -->
          <n-collapse>
            <n-collapse-item title="原始结果 JSON">
              <pre style="max-height:300px;overflow:auto;font-size:12px;margin:0;background:#fafafa;padding:8px;border-radius:4px">{{ formatJson(detail.result_json) }}</pre>
            </n-collapse-item>
          </n-collapse>
        </template>
      </n-spin>
    </n-modal>
  </CommonPage>
</template>

<script setup>
import { ref, reactive, h, computed } from 'vue'
import { NButton, NCollapse, NCollapseItem, NDataTable, NDescriptions, NDescriptionsItem, NInput, NModal, NSelect, NSpace, NSpin, NTag } from 'naive-ui'
import CommonPage from '@/components/page/CommonPage.vue'
import CrudTable from '@/components/table/CrudTable.vue'
import api from '@/api/operationJob'

const $table = ref(null)
const queryItems = reactive({})
const showDetail = ref(false)
const detail = ref(null)


async function fetchJobs(params) {
  const r = await api.getList({ page: params.page, page_size: params.page_size, ...params })
  return { data: r.data || [], total: r.total || 0 }
}

const actionOptions = [
  { value: '', label: '全部' },
  { value: 'dns', label: 'DNS' },
  { value: 'dynadot_ns', label: 'Dynadot NS' },
  { value: 'redirect', label: '301重定向' },
  { value: 'provision', label: '1Panel建站' },
  { value: 'assign_gmail', label: '分配Gmail' },
  { value: 'woo_import', label: '产品导入' },
  { value: 'collect', label: '采集' },
  { value: 'collect_shopify', label: 'Shopify采集' },
  { value: 'hub_create_env', label: 'Hub创建环境' },
  { value: 'hub_create_account', label: 'Hub创建账号' },
  { value: 'hub_update_env', label: 'Hub更新环境' },
  { value: 'hub_wp_login', label: 'Hub登录WP' },
  { value: 'hub_gmc_check', label: 'Hub GMC检查' },
]
const actionTypeLabel = Object.fromEntries(actionOptions.map(o => [o.value, o.label]))

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'pending', label: '等待中' },
  { value: 'running', label: '执行中' },
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
]

const statusTagMap = { pending: 'default', running: 'info', success: 'success', failed: 'error', cancelled: 'warning' }
function statusTag(s) { return statusTagMap[s] || 'default' }

const columns = [
  { title: '序号', key: 'index', width: 50, align: 'center', render: (_, index) => index + 1 },
  { title: '资源', key: 'resource_type', width: 80, render(row) { return row.resource_type + ' #' + row.resource_id } },
  { title: '域名', key: 'domain', width: 140, ellipsis: { tooltip: true } },
  { title: '操作', key: 'action_type', width: 100, render: row => actionTypeLabel[row.action_type] || row.action_type },
  { title: '状态', key: 'status', width: 70, render(row) { return h(NTag, { type: statusTag(row.status), size: 'small' }, () => row.status) } },
  { title: '步骤', key: 'step', width: 140, ellipsis: { tooltip: true }, render(row) { return (row.step || '0') + '/' + (row.total_steps || '1') } },
  { title: '批次', key: 'batch_id', width: 100, ellipsis: { tooltip: true } },
  { title: '节点', key: 'worker_name', width: 80 },
  { title: '时间', key: 'created_at', width: 140 },
  {
    title: '操作', key: 'actions', width: 80,
    render(row) {
      return h(NButton, { size: 'small', onClick: () => { detail.value = row; showDetail.value = true } }, () => '详情')
    }
  },
]

function formatJson(str) {
  try { return JSON.stringify(JSON.parse(str), null, 2) } catch { return str }
}

const providerName = computed(() => {
  if (!detail.value?.result_json) return '-'
  try {
    const obj = JSON.parse(detail.value.result_json)
    return obj?.provider?.provider_name || '-'
  } catch { return '-' }
})

// 解析 result_json 为汇总标签（批量操作）
const resultSummary = computed(() => {
  if (!detail.value?.result_json) return null
  try {
    const obj = JSON.parse(detail.value.result_json)
    const items = []
    const m = { deleted_from_db: { label: 'DB删除', type: 'info' }, '1panel_deleted': { label: '1Panel已删', type: 'success' }, '1panel_failed': { label: '1Panel失败', type: 'error' }, '1panel_skipped': { label: '1Panel跳过', type: 'warning' } }
    for (const [k, v] of Object.entries(m)) {
      if (obj[k] !== undefined) items.push({ label: v.label, count: obj[k], type: v.type })
    }
    return items.length ? items : null
  } catch { return null }
})

// 解析批量结果列表
const resultList = computed(() => {
  if (!detail.value?.result_json) return []
  try {
    const obj = JSON.parse(detail.value.result_json)
    if (Array.isArray(obj.results) && obj.results.length) {
      return obj.results.map((r, i) => ({ ...r, _idx: i + 1 }))
    }
    return []
  } catch { return [] }
})

const resultColumns = [
  { title: '#', key: '_idx', width: 40, align: 'center' },
  { title: '域名', key: 'domain', ellipsis: { tooltip: true } },
  {
    title: '状态', key: 'status', width: 90, align: 'center',
    render(row) {
      const m = { deleted: 'success', error: 'error', not_found: 'warning', skip: 'default', exception: 'error' }
      const labels = { deleted: '已删除', error: '失败', not_found: '未找到', skip: '跳过', exception: '异常' }
      return h(NTag, { type: m[row.status] || 'default', size: 'small' }, () => labels[row.status] || row.status)
    }
  },
  { title: '详情', key: 'detail', ellipsis: { tooltip: true }, minWidth: 100 },
]
</script>
