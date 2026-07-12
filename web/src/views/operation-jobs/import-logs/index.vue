<template>
  <CommonPage show-header title="导入记录">
    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="fetchLogs"
    >
      <template #queryBar>
        <n-select v-model:value="queryItems.import_type" :options="typeOptions" placeholder="导入类型" clearable style="width:160px" />
        <n-input v-model:value="queryItems.file_name" placeholder="文件名" clearable style="width:200px" @keypress.enter="$table?.handleSearch()" />
      </template>
      <template #queryBarActions>
        <n-upload accept=".csv,.xlsx" :show-file-list="false" @change="handleUpload">
          <n-button type="primary">上传 CSV/XLSX 导入</n-button>
        </n-upload>
        <n-select v-model:value="uploadType" :options="typeOptions.filter(t => t.value)" placeholder="选择导入类型" style="width:160px" />
        <n-button secondary @click="downloadTemplate">下载模板</n-button>
      </template>
    </CrudTable>

    <!-- 错误详情弹窗 -->
    <n-modal v-model:show="showErrors" title="错误详情" preset="dialog">
      <pre style="max-height:400px;overflow:auto;font-size:12px">{{ errorDetail }}</pre>
    </n-modal>
  </CommonPage>
</template>

<script setup>
import { ref, h, computed } from 'vue'
import { NButton, NInput, NModal, NSelect, NTag, NUpload, useMessage } from 'naive-ui'
import CommonPage from '@/components/page/CommonPage.vue'
import CrudTable from '@/components/table/CrudTable.vue'
import API from '~/src/api/importJob'

const message = useMessage()
const $table = ref(null)
const queryItems = ref({})
const uploadType = ref('sites')
const showErrors = ref(false)
const errorDetail = ref('')

async function fetchLogs(params) {
  const r = await API.getList({ page: params.page, page_size: params.page_size, ...params })
  return { data: r.data || [], total: r.total || 0 }
}

const typeOptions = [
  { value: '', label: '全部' },
  { value: 'sites', label: '站点' },
  { value: 'gmail', label: 'Gmail' },
  { value: 'shopify_sources', label: '采集源' },
  { value: 'shopify_products', label: '商品' },
]

const statusMap = { pending: 'default', processing: 'info', success: 'success', partial: 'warning', failed: 'error' }

const columns = [
  { title: '类型', key: 'import_type', width: 100 },
  { title: '文件名', key: 'file_name', ellipsis: { tooltip: true }, width: 200 },
  { title: '状态', key: 'status', width: 80, render(r) { return h(NTag, { type: statusMap[r.status] || 'default', size: 'small' }, r.status) } },
  { title: '成功', key: 'success_count', width: 60 },
  { title: '失败', key: 'fail_count', width: 60 },
  { title: '时间', key: 'created_at', width: 150 },
  {
    title: '错误', key: 'error_report', width: 80,
    render(r) {
      if (!r.error_report || r.error_report === '[]') return ''
      return h(NButton, { size: 'small', quaternary: true, type: 'error', onClick: () => { errorDetail.value = formatJson(r.error_report); showErrors.value = true } }, '查看')
    }
  },
]

function formatJson(s) {
  try { return JSON.stringify(JSON.parse(s), null, 2) } catch { return s }
}

function downloadTemplate() {
  if (!uploadType.value) { message.warning('请先选择导入类型'); return }
  API.downloadTemplate(uploadType.value)
}

async function handleUpload({ file }) {
  if (!uploadType.value) {
    message.warning('请选择导入类型')
    return
  }
  const formData = new FormData()
  formData.append('file', file.file)
  try {
    const r = await API.upload(uploadType.value, formData)
    message.success(`导入完成: 成功 ${r.success} 条, 失败 ${r.fail} 条`)
    $table.value?.handleSearch()
  } catch (e) {
    message.error(`导入失败: ${e}`)
  }
}
</script>
