<template>
  <CommonPage show-header title="Feed 文件管理">
    <template #action>
      <div style="margin-left: auto;">
        <n-upload :show-file-list="false" accept=".csv,.xml,.txt" :custom-request="handleUpload" :disabled="uploading">
          <n-button type="primary" :loading="uploading">
            <span style="display:inline-flex;align-items:center;gap:6px">
              <span class="i-mdi:cloud-upload-outline" />
              上传 Feed 文件
            </span>
          </n-button>
        </n-upload>
      </div>
    </template>

    <n-space vertical :size="16">
      <!-- 源文件列表 -->
      <n-card title="源文件" size="small" rounded-10>
        <n-data-table
          :columns="sourceColumns"
          :data="sourceData"
          :loading="sourceLoading"
          :pagination="sourcePagi"
          :row-key="(r) => r.id"
          size="small"
          @update:page="(p) => { sourcePagi.page = p; loadSources() }"
          @update:page-size="(s) => { sourcePagi.pageSize = s; sourcePagi.page = 1; loadSources() }"
        />
      </n-card>

      <!-- 已处理文件列表 -->
      <n-card title="已处理 Feed（可下载）" size="small" rounded-10>
        <n-data-table
          :columns="processedColumns"
          :data="processedData"
          :loading="procLoading"
          :pagination="procPagi"
          :row-key="(r) => r.id"
          size="small"
          @update:page="(p) => { procPagi.page = p; loadProcessed() }"
          @update:page-size="(s) => { procPagi.pageSize = s; procPagi.page = 1; loadProcessed() }"
        />
      </n-card>

      <!-- 创建新Feed弹窗 -->
      <n-modal v-model:show="showCreate" preset="card" title="创建新 Feed" style="width: 520px">
        <n-space vertical :size="14">
          <n-text>源文件: <b>{{ createTarget?.original_name }}</b></n-text>
          <n-form-item label="旧域名（原始）">
            <n-input v-model:value="createSourceDomain" placeholder="自动检测" />
          </n-form-item>
          <n-form-item label="新域名（替换为）" required>
            <n-input
              v-model:value="createTargetDomain"
              :placeholder="defaultDomain ? `默认: ${defaultDomain}` : '请输入新域名'"
            />
          </n-form-item>
          <n-alert v-if="createResult" type="success" title="创建成功">
            <n-space vertical :size="4">
              <n-text>共替换 {{ createResult.replace_count }} 处</n-text>
              <n-text>{{ createResult.source_domain }} → {{ createResult.target_domain }}</n-text>
            </n-space>
          </n-alert>
        </n-space>
        <template #footer>
          <n-space justify="end">
            <n-button @click="showCreate = false">{{ createResult ? '关闭' : '取消' }}</n-button>
            <n-button
              v-if="!createResult"
              type="primary"
              :loading="creating"
              :disabled="!createTargetDomain"
              @click="confirmCreate"
            >
              开始替换
            </n-button>
          </n-space>
        </template>
      </n-modal>
    </n-space>
  </CommonPage>
</template>

<script setup>
import { h, ref, reactive, onMounted } from 'vue'
import {
  NAlert, NButton, NCard, NDataTable, NFormItem, NInput, NModal,
  NSpace, NTag, NText, NUpload, useMessage,
} from 'naive-ui'
import { useClipboard } from '@vueuse/core'
import api from '@/api/site-pipeline'

const message = useMessage()
const { copy } = useClipboard()

// ── 源文件列表 ──
const sourceData = ref([])
const sourceLoading = ref(false)
const sourcePagi = reactive({ page: 1, pageSize: 20, itemCount: 0, showSizePicker: true, pageSizes: [10, 20, 50] })

// ── 已处理列表 ──
const processedData = ref([])
const procLoading = ref(false)
const procPagi = reactive({ page: 1, pageSize: 20, itemCount: 0, showSizePicker: true, pageSizes: [10, 20, 50] })

// ── 创建弹窗 ──
const showCreate = ref(false)
const creating = ref(false)
const createTarget = ref(null)
const createSourceDomain = ref('')
const createTargetDomain = ref('')
const createResult = ref(null)
const defaultDomain = ref('')

// ── 源文件列 ──
const sourceColumns = [
  { title: '序号', key: 'index', width: 40, align: 'center', render: (_, index) => index + 1 },
  { title: '文件名', key: 'original_name', width: 170, ellipsis: { tooltip: true } },
  {
    title: '检测域名', key: 'source_domain', width: 150, ellipsis: { tooltip: true },
    render: (r) => r.source_domain || h(NText, { depth: 3 }, '未检测到'),
  },
  { title: '类型', key: 'file_type', width: 160 },
  {
    title: '大小', key: 'file_size', width: 60,
    render: (r) => {
      const kb = r.file_size / 1024
      return kb > 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb.toFixed(1)} KB`
    },
  },
  { title: '上传时间', key: 'created_at', width: 140 },
  {
    title: '操作', key: 'actions', width: 166, fixed: 'right',
    render: (r) => h('div', { style: 'display:flex;gap:4px' }, [
      h(NButton, { size: 'tiny', type: 'primary', style: 'width:90px', onClick: () => openCreate(r) }, '创建新Feed'),
      h(NButton, { size: 'tiny', type: 'error', style: 'width:48px', onClick: () => doDelete(r.id) }, '删除'),
    ]),
  },
]

// ── 已处理文件列 ──
const processedColumns = [
  { title: '序号', key: 'index', width: 40, align: 'center', render: (_, index) => index + 1 },
  { title: '原始文件名', key: 'original_name', width: 170, ellipsis: { tooltip: true } },
  {
    title: '新文件名', key: 'processed_name', width: 150, ellipsis: { tooltip: true },
    render: (r) => r.processed_name || '-',
  },
  {
    title: '域名变更', key: 'domains', width: 160, ellipsis: { tooltip: true },
    render: (r) => h(NText, { depth: 2 }, `${r.source_domain || '?'} → ${r.target_domain || '?'}`),
  },
  {
    title: '替换次数', key: 'replace_count', width: 60,
    render: (r) => r.replace_count > 0 ? r.replace_count : '-',
  },
  { title: '创建时间', key: 'created_at', width: 140 },
  {
    title: '操作', key: 'actions', width: 166, fixed: 'right',
    render: (r) => h('div', { style: 'display:flex;gap:4px' }, [
      h(NButton, {
        size: 'tiny', type: 'success', style: 'width:90px',
        disabled: !r.download_url,
        onClick: () => copyDownloadUrl(r.download_url),
      }, '复制链接'),
      h(NButton, { size: 'tiny', type: 'error', style: 'width:48px', onClick: () => doDelete(r.id) }, '删除'),
    ]),
  },
]

onMounted(() => {
  loadSources()
  loadProcessed()
  loadDefaultDomain()
})

async function loadSources() {
  sourceLoading.value = true
  try {
    const res = await api.getFeedSourceList({ page: sourcePagi.page, page_size: sourcePagi.pageSize })
    sourceData.value = res.data || []
    sourcePagi.itemCount = res.total || 0
  } catch (_) {} finally { sourceLoading.value = false }
}

async function loadProcessed() {
  procLoading.value = true
  try {
    const res = await api.getFeedProcessedList({ page: procPagi.page, page_size: procPagi.pageSize })
    processedData.value = res.data || []
    procPagi.itemCount = res.total || 0
  } catch (_) {} finally { procLoading.value = false }
}

async function loadDefaultDomain() {
  try {
    const res = await api.getFeedDefaultDomain()
    defaultDomain.value = res.data?.domain || ''
  } catch (_) {}
}

// 上传
const uploading = ref(false)

async function handleUpload({ file }) {
  if (!file.file) return
  uploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', file.file)
    await api.uploadFeed(formData)
    message.success('上传成功')
    loadSources()
  } catch (_) {
    message.error('上传失败')
  } finally {
    uploading.value = false
  }
}

// 打开创建弹窗
function openCreate(row) {
  createTarget.value = row
  createSourceDomain.value = row.source_domain || ''
  createTargetDomain.value = defaultDomain.value
  createResult.value = null
  showCreate.value = true
}

// 确认创建
async function confirmCreate() {
  creating.value = true
  try {
    const res = await api.createFeed(
      createTarget.value.id,
      createTargetDomain.value,
      createSourceDomain.value,
    )
    createResult.value = res.data
    message.success('新 Feed 创建成功')
    loadSources()
    loadProcessed()
  } catch (_) {
    message.error('创建失败')
  } finally {
    creating.value = false
  }
}

// 复制下载链接
function copyDownloadUrl(url) {
  if (!url) return
  copy(window.location.origin + url)
  message.success('下载链接已复制')
}

// 删除
async function doDelete(id) {
  try {
    await api.deleteFeed(id)
    message.success('已删除')
    loadSources()
    loadProcessed()
  } catch (_) {
    message.error('删除失败')
  }
}
</script>
