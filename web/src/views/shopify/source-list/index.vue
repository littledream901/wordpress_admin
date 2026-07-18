<template>
  <CommonPage show-header title="Shopify 待采集列表">
    <template #action>
      <n-space>
        <n-button type="primary" @click="handleAdd">新增采集源</n-button>
        <n-button @click="showBatchImport = true">批量导入</n-button>
      </n-space>
    </template>

    <CrudTable
      ref="crudRef"
      :columns="columns"
      :query-items="queryItems"
      :get-data="getData"
      @on-checked="onChecked"
    >
      <template #queryBar>
        <n-input
          v-model:value="queryItems.source_url"
          placeholder="URL 搜索"
          clearable
          style="width: 280px"
          @keyup.enter="crudRef.handleSearch()"
        />
      </template>
      <template #queryBarActions>
        <template v-if="checkedRowKeys.length">
          <n-divider vertical />
          <span style="white-space: nowrap; font-size: 14px">已选 {{ checkedRowKeys.length }} 项</span>
          <n-button type="primary" size="small" @click="handleBatchCollect">批量采集</n-button>
          <n-button type="error" size="small" @click="handleBatchDelete">批量删除</n-button>
        </template>
      </template>
    </CrudTable>

    <!-- 新增 / 编辑弹窗 -->
    <CrudModal v-model:visible="modalVisible" :title="modalTitle" :loading="modalLoading" width="480px" @save="handleSave">
      <n-form ref="modalFormRef" :model="modalForm" label-placement="left" label-width="90">
        <n-form-item label="来源URL" path="source_url" :rule="{ required: true, message: '必填' }">
          <n-input v-model:value="modalForm.source_url" placeholder="https://store.myshopify.com" />
        </n-form-item>
        <n-form-item label="类型" v-if="modalForm.source_url">
          <n-tag :type="detectedType === 'product' ? 'info' : detectedType === 'collection' ? 'success' : 'error'" size="small">
            {{ detectedType === 'product' ? '单品采集' : detectedType === 'collection' ? '集合采集' : '不支持全店采集，需含 /collections/xxx 或 /products/xxx' }}
          </n-tag>
        </n-form-item>
        <n-form-item label="最大数量">
          <n-input-number v-model:value="modalForm.max_products" :min="0" placeholder="0=不限制" />
        </n-form-item>
        <n-form-item label="备注">
          <n-input v-model:value="modalForm.remark" type="textarea" />
        </n-form-item>
      </n-form>
    </CrudModal>

    <!-- 批量导入弹窗 -->
    <n-modal v-model:show="showBatchImport" preset="card" title="批量导入采集源" style="max-width: 680px">
      <n-space vertical :size="12">
        <n-text depth="3">每行一个 Shopify 链接，支持集合链接和单品链接</n-text>
        <n-input
          v-model:value="batchImportText"
          type="textarea"
          :rows="8"
          placeholder="https://store.myshopify.com/collections/best-sellers&#10;https://store.myshopify.com/products/sample-product"
          @update:value="onBatchImportTextChange"
        />
        <!-- 预览表格 -->
        <n-data-table
          v-if="batchImportPreview.length"
          :columns="batchImportPreviewColumns"
          :data="batchImportPreview"
          :max-height="200"
          size="small"
        />
        <n-text v-if="batchImportPreview.length" depth="3" style="font-size:12px">
          已解析 {{ batchImportPreview.length }} 个链接，其中
          <n-tag type="success" size="tiny" :bordered="false">{{ batchImportPreview.filter(r => r.valid).length }} 有效</n-tag>
          <n-tag type="error" size="tiny" :bordered="false" v-if="batchImportPreview.filter(r => !r.valid).length">{{ batchImportPreview.filter(r => !r.valid).length }} 无效</n-tag>
        </n-text>
        <!-- 导入结果 -->
        <n-alert v-if="batchImportResult" :type="batchImportResultType" :title="batchImportResult" />
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showBatchImport = false; batchImportText = ''; batchImportPreview.length = 0; batchImportResult = ''">取消</n-button>
          <n-button type="primary" :loading="batchImportLoading" :disabled="!batchImportPreview.some(r => r.valid)" @click="doBatchImport">导入有效链接 ({{ batchImportPreview.filter(r => r.valid).length }})</n-button>
        </n-space>
      </template>
    </n-modal>
    <!-- 批量采集结果弹窗 -->
    <n-modal v-model:show="showBatchCollectResult" preset="card" title="批量采集 — 已提交后台任务" style="max-width: 550px">
      <n-space align="center" style="margin-bottom:10px">
        <n-tag type="success" size="small" :bordered="false">已提交 {{ batchCollectSuccess }}</n-tag>
        <n-tag type="error" size="small" :bordered="false" v-if="batchCollectFail">失败 {{ batchCollectFail }}</n-tag>
        <n-text depth="3" style="font-size:13px">总计 {{ batchCollectResults.length }} 项</n-text>
      </n-space>
      <n-text depth="3" style="font-size:12px;display:block;margin-bottom:8px">
        可在 <n-a @click="showBatchCollectResult=false;router.push('/operation-jobs/job-list')" style="cursor:pointer">任务中心</n-a> 查看采集进度
      </n-text>
      <n-data-table
        :columns="[{title:'源ID',key:'source_id',width:60},{title:'任务ID',key:'job_id',width:60},{title:'状态',key:'status',width:80,render:(r)=>h(NTag,{type:r.ok?'success':'error',size:'small'},{default:()=>r.ok?'后台运行中':'失败'})},{title:'详情',key:'error',ellipsis:{tooltip:true}}]"
        :data="batchCollectResults"
        :max-height="300"
        size="small"
      />
      <template #footer>
        <n-space justify="end">
          <n-button type="primary" size="small" @click="showBatchCollectResult=false;router.push('/operation-jobs/job-list')">查看任务中心</n-button>
          <n-button @click="showBatchCollectResult=false">关闭</n-button>
        </n-space>
      </template>
    </n-modal>
  </CommonPage>
</template>

<script setup>
import { h, reactive, ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NTag, NSpace, useMessage } from 'naive-ui'
import api from '@/api/shopify'
import CommonPage from '@/components/page/CommonPage.vue'
import CrudTable from '@/components/table/CrudTable.vue'
import CrudModal from '@/components/table/CrudModal.vue'

const message = useMessage()
const router = useRouter()

// ─── 搜索 ───
const queryItems = reactive({ source_url: '' })

// ─── 表格 ───
const crudRef = ref(null)
const checkedRowKeys = ref([])

const getData = async (params) => {
  const res = await api.getSourceList({
    page: params.page,
    page_size: params.page_size,
    source_url: params.source_url,
  })
  return { data: res?.data ?? [], total: res?.total ?? 0 }
}

function onChecked(keys) { checkedRowKeys.value = keys }

function statusTag(status) {
  const map = { pending: 'default', collected: 'success', 'collect_failed': 'error' }
  const type = Object.entries(map).find(([k]) => (status || '').startsWith(k))?.[1] || 'default'
  return h(NTag, { type, size: 'small' }, { default: () => status || 'pending' })
}

// 自动推断采集类型（仅支持集合和单品）
const detectedType = computed(() => {
  const u = modalForm.value?.source_url?.trim() || ''
  if (u.includes('/products/') && u.split('/').length >= 5) return 'product'
  if (u.includes('/collections/') && u.split('/').length >= 5) return 'collection'
  return 'invalid'
})

// URL 类型检测（用于批量导入）
function detectUrlType(url) {
  const u = url.trim()
  if (!u) return { type: 'invalid', label: '空行' }
  if (!u.startsWith('http')) return { type: 'invalid', label: '缺少 http(s)://' }
  if (u.includes('/products/') && u.split('/').length >= 5) return { type: 'product', label: '单品' }
  if (u.includes('/collections/') && u.split('/').length >= 5) return { type: 'collection', label: '集合' }
  return { type: 'invalid', label: '不支持的URL格式（需含 /collections/ 或 /products/）' }
}

// ─── 批量导入 ───
const showBatchImport = ref(false)
const batchImportText = ref('')
const batchImportPreview = ref([])
const batchImportLoading = ref(false)
const batchImportResult = ref('')
const batchImportResultType = ref('success')

const batchImportPreviewColumns = [
  { title: '序号', key: 'index', width: 50 },
  { title: 'URL', key: 'url', ellipsis: { tooltip: true }, width: 300 },
  { title: '类型', key: 'typeLabel', width: 60, render: (r) => h(NTag, { type: r.valid ? 'success' : 'error', size: 'small' }, { default: () => r.typeLabel }) },
  { title: '状态', key: 'valid', width: 50, render: (r) => h(NTag, { type: r.valid ? 'success' : 'error', size: 'small' }, { default: () => r.valid ? '有效' : '无效' }) },
]

function onBatchImportTextChange() {
  batchImportResult.value = ''
  const lines = batchImportText.value.split('\n').filter(l => l.trim())
  batchImportPreview.value = lines.map((url, i) => {
    const { type, label } = detectUrlType(url)
    return { index: i + 1, url: url.trim(), type, typeLabel: label, valid: type !== 'invalid' }
  })
}

async function doBatchImport() {
  const validItems = batchImportPreview.value.filter(r => r.valid)
  if (!validItems.length) {
    batchImportResult.value = '没有有效的链接可导入'
    batchImportResultType.value = 'warning'
    return
  }
  batchImportLoading.value = true
  batchImportResult.value = ''
  try {
    const items = validItems.map(r => ({
      source_url: r.url,
      source_type: r.type,
      max_products: 0,
    }))
    const res = await api.batchCreateSource(items)
    const data = res?.data ?? {}
    const created = data.success ?? 0
    const skipped = data.fail ?? 0
    batchImportResult.value = `导入完成：成功创建 ${created} 个，跳过重复 ${skipped} 个`
    batchImportResultType.value = created > 0 ? 'success' : 'warning'
    if (created > 0) {
      batchImportText.value = ''
      batchImportPreview.value = []
      crudRef.value?.handleSearch()
    }
  } catch (e) {
    batchImportResult.value = e?.response?.data?.msg || '批量导入失败'
    batchImportResultType.value = 'error'
  } finally {
    batchImportLoading.value = false
  }
}

const columns = [
  {
    type: 'selection',
    multiple: true,
    disabled: () => false,
  },
  { title: '序号', key: 'index', width: 50, align: 'center', render: (_, index) => index + 1 },
  { title: '来源URL', key: 'source_url', ellipsis: { tooltip: true }, width: 300 },
  { title: '类型', key: 'source_type', width: 100 },
  { title: '状态', key: 'status', width: 120, render: (r) => statusTag(r.status) },
  { title: '最大数量', key: 'max_products', width: 80 },
  { title: '最近采集', key: 'last_collect_count', width: 80 },
  {
    title: '操作', key: 'actions', width: 200,
    render: (row) => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'tiny', onClick: () => handleEdit(row) }, { default: () => '编辑' }),
        h(NButton, { size: 'tiny', type: 'primary', onClick: () => doCollect(row) }, { default: () => '采集' }),
        h(NButton, { size: 'tiny', type: 'error', onClick: () => doDelete(row) }, { default: () => '删除' }),
      ],
    }),
  },
]

// ─── 新增 / 编辑 ───
const modalVisible = ref(false)
const modalLoading = ref(false)
const modalAction = ref('add')
const modalTitle = computed(() => (modalAction.value === 'add' ? '新增采集源' : '编辑采集源'))
const modalForm = ref({ source_url: '', source_type: 'collection', max_products: 0, remark: '' })
const modalFormRef = ref(null)

function handleAdd() {
  modalAction.value = 'add'
  modalForm.value = { source_url: '', source_type: 'collection', max_products: 0, remark: '' }
  modalVisible.value = true
}

function handleEdit(row) {
  modalAction.value = 'edit'
  modalForm.value = { ...row }
  modalVisible.value = true
}

async function handleSave() {
  try {
    modalLoading.value = true
    if (modalAction.value === 'add') {
      await api.createSource(modalForm.value)
      message.success('新增成功')
    } else {
      await api.updateSource(modalForm.value)
      message.success('编辑成功')
    }
    modalVisible.value = false
    crudRef.value?.handleSearch()
  } catch (e) {
    message.error(e?.response?.data?.msg || '操作失败')
  } finally {
    modalLoading.value = false
  }
}

// ─── 单条操作 ───
async function doCollect(row) {
  try {
    const res = await api.collectSource(row.id)
    if (res?.data?.ok !== undefined && !res.data.ok) {
      message.warning(res?.data?.error || '采集失败')
    } else {
      message.success(`采集完成: ${res?.data?.count ?? 0} 条`)
    }
    crudRef.value?.handleSearch()
  } catch (e) {
    message.error(e?.response?.data?.msg || '采集失败')
  }
}

async function doDelete(row) {
  try {
    await api.deleteSource(row.id)
    message.success('删除成功')
    crudRef.value?.handleSearch()
  } catch (e) {
    message.error(e?.response?.data?.msg || '删除失败')
  }
}

// ─── 批量操作 ───
const showBatchCollectResult = ref(false)
const batchCollectResults = ref([])
const batchCollectSuccess = ref(0)
const batchCollectFail = ref(0)

async function handleBatchCollect() {
  if (!checkedRowKeys.value.length) return
  try {
    const res = await api.batchCollectSource(checkedRowKeys.value)
    const d = res?.data ?? {}
    batchCollectResults.value = d.results ?? []
    batchCollectSuccess.value = d.success ?? 0
    batchCollectFail.value = d.fail ?? 0
    showBatchCollectResult.value = true
    message.success(`已提交 ${batchCollectSuccess.value} 个后台采集任务`)
    checkedRowKeys.value = []
    crudRef.value?.handleSearch()
  } catch (e) {
    message.error(e?.response?.data?.msg || '批量采集失败')
  }
}

async function handleBatchDelete() {
  if (!checkedRowKeys.value.length) return
  try {
    const res = await api.batchDeleteSource(checkedRowKeys.value)
    message.success(`已删除 ${res?.data?.deleted ?? 0} 条`)
    checkedRowKeys.value = []
    crudRef.value?.handleSearch()
  } catch (e) {
    message.error(e?.response?.data?.msg || '批量删除失败')
  }
}

// ─── 初始化 ───
onMounted(() => {
  crudRef.value?.handleSearch()
})
</script>
