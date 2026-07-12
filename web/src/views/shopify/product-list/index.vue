<template>
  <CommonPage title="Shopify 产品列表">
    <CrudTable ref="$table" v-model:query-items="queryItems" :get-data="api.getProductList" :columns="columns" :pagination="pagination">
      <template #queryBar>
        <n-input v-model:value="queryItems.title" placeholder="产品标题搜索" clearable style="width: 240px" @keyup.enter="$table?.handleSearch()" />
      </template>
      <template #queryBarActions>
        <template v-if="selectedIds.length">
          <n-divider vertical />
          <span style="white-space: nowrap; font-size: 14px">已选 {{ selectedIds.length }} 项</span>
          <n-popover :show="showBatchMenu" trigger="manual" placement="bottom" :show-arrow="false" @clickoutside="showBatchMenu = false">
            <template #trigger>
              <n-button @click="showBatchMenu = !showBatchMenu">
                批量操作
                <template #icon>
                  <TheIcon icon="mdi:chevron-down" :size="16" />
                </template>
              </n-button>
            </template>
            <n-button-group vertical size="small" style="text-align: left">
              <n-button @click="handleBatchAction('import')" style="justify-content: flex-start">
                <template #icon>
                  <TheIcon icon="mdi:import" :size="18" />
                </template>
                批量导入到站点
              </n-button>
              <n-button @click="handleBatchAction('delete')" style="justify-content: flex-start">
                <template #icon>
                  <TheIcon icon="mdi:delete" :size="18" />
                </template>
                批量删除
              </n-button>
            </n-button-group>
          </n-popover>
        </template>
      </template>
    </CrudTable>

    <!-- 域名选择弹窗 -->
    <n-modal v-model:show="showDomainModal" title="选择导入目标站点">
      <n-card style="width: 500px" title="选择站点域名">
        <n-select
          v-model:value="selectedDomain"
          filterable
          placeholder="搜索站点域名"
          :options="siteOptions"
          :loading="siteLoading"
          @search="searchSites"
        />
        <template #footer>
          <n-space justify="end">
            <n-button @click="showDomainModal = false">取消</n-button>
            <n-button type="primary" :disabled="!selectedDomain" @click="confirmImport">确认导入</n-button>
          </n-space>
        </template>
      </n-card>
    </n-modal>

    <!-- JSON 详情弹窗 -->
    <n-modal
      v-model:show="showJsonModal"
      class="json-modal"
      :title="`产品 JSON - #${currentProductId}`"
      preset="card"
      style="max-width: 820px; width: calc(100vw - 40px)"
      size="huge"
      :bordered="false"
    >
      <template #header-extra>
        <n-button size="small" secondary @click="copyJson">
          <template #icon>
            <TheIcon icon="mdi:content-copy" :size="16" />
          </template>
          复制
        </n-button>
      </template>

      <div v-if="jsonError" class="json-error">
        <TheIcon icon="mdi:alert-circle" :size="20" />
        <span>JSON 解析失败: {{ jsonError }}</span>
        <pre class="json-raw">{{ currentRawJson }}</pre>
      </div>

      <div v-else-if="jsonTree.length" class="json-viewer" ref="jsonViewer">
        <template v-for="(node, i) in jsonTree" :key="i">
          <div class="json-line" :style="{ paddingLeft: (node.depth * 20 + 12) + 'px' }">
            <span
              v-if="node.key !== undefined"
              class="json-key"
              @dblclick="copyJsonValue(node.key)"
            >"{{ node.key }}"</span>
            <span v-if="node.key !== undefined" class="json-colon">: </span>
            <span v-if="node.value !== undefined" :class="jsonValueClass(node)" @dblclick="copyJsonValue(node.value)">{{ node.value }}</span>
            <span v-else-if="node.bracket" class="json-bracket">{{ node.bracket }}</span>
          </div>
        </template>
      </div>

      <n-empty v-else description="无 JSON 数据" size="small" />

      <template #footer>
        <n-space justify="end">
          <n-button @click="showJsonModal = false">关闭</n-button>
        </n-space>
      </template>
    </n-modal>
  </CommonPage>
</template>

<script setup>
import { h, reactive, ref, computed, onMounted } from 'vue'
import {
  NButton, NButtonGroup, NCard, NCheckbox, NDivider,
  NEmpty, NInput, NModal, NPopconfirm,
  NPopover, NSelect, NSpace, NTag, useMessage,
} from 'naive-ui'
import api from '@/api/shopify'
import siteApi from '@/api/site-pipeline'
import TheIcon from '@/components/icon/TheIcon.vue'
import { buildJsonTree, jsonValueClass, injectJsonStyles } from '@/utils/jsonTree'

injectJsonStyles()

const queryItems = reactive({ title: '' })
const pagination = reactive({ page: 1, pageSize: 10, showSizePicker: true, pageSizes: [10, 20, 50] })
const $table = ref(null)
const selectedIds = ref([])
const selectedDomain = ref(null)
const siteOptions = ref([])
const siteLoading = ref(false)
const showDomainModal = ref(false)
const importMode = ref('') // 'single' | 'batch'
const importRowData = ref(null)
const showBatchMenu = ref(false)

// ─── JSON 弹窗 ───
const showJsonModal = ref(false)
const currentProductId = ref(0)
const currentRawJson = ref('')
const jsonTree = ref([])
const jsonError = ref('')

const message = useMessage()

onMounted(() => {
  $table.value?.handleSearch()
})

const reload = () => $table.value?.handleSearch()

const toggle = (id, checked) => {
  selectedIds.value = checked
    ? [...new Set([...selectedIds.value, id])]
    : selectedIds.value.filter(x => x !== id)
}

const toggleAll = (checked) => {
  const rows = $table.value?.tableData || []
  if (checked) {
    const ids = rows.map(r => r.id)
    selectedIds.value = [...new Set([...selectedIds.value, ...ids])]
  } else {
    const pageIds = new Set(rows.map(r => r.id))
    selectedIds.value = selectedIds.value.filter(id => !pageIds.has(id))
  }
}

const isAllChecked = computed(() => {
  const rows = $table.value?.tableData || []
  return rows.length > 0 && rows.every(r => selectedIds.value.includes(r.id))
})

const searchSites = async (query = '') => {
  siteLoading.value = true
  try {
    const res = await siteApi.getSiteList({ page: 1, page_size: 50, domain: query })
    const items = res?.data || []
    siteOptions.value = items.map(s => ({ label: s.domain, value: s.domain }))
  } catch (e) {
    message.error('加载站点失败')
  }
  siteLoading.value = false
}

const importOne = async (row) => {
  selectedDomain.value = null
  siteOptions.value = []
  importMode.value = 'single'
  importRowData.value = row
  searchSites()
  showDomainModal.value = true
}

const batchImport = async () => {
  if (!selectedIds.value.length) return message.warning('请先选择产品')
  selectedDomain.value = null
  siteOptions.value = []
  importMode.value = 'batch'
  searchSites()
  showDomainModal.value = true
}

const confirmImport = async () => {
  if (!selectedDomain.value) return
  try {
    if (importMode.value === 'single') {
      await api.importProductToSite(importRowData.value.id, { domain: selectedDomain.value })
      message.success('已触发单产品导入')
    } else {
      await api.batchImportToSite({ product_ids: selectedIds.value, domain: selectedDomain.value })
      message.success('已触发批量导入')
      selectedIds.value = []
    }
    showDomainModal.value = false
    reload()
  } catch (e) {
    message.error(e?.response?.data?.msg || '导入失败')
  }
}

const deleteOne = async (row) => {
  try {
    await api.deleteProduct(row.id)
    message.success('删除成功')
    selectedIds.value = selectedIds.value.filter(id => id !== row.id)
    reload()
  } catch (e) {
    message.error(e?.response?.data?.msg || '删除失败')
  }
}

const batchDelete = async () => {
  if (!selectedIds.value.length) return message.warning('请先选择产品')
  try {
    const res = await api.batchDeleteProducts(selectedIds.value)
    message.success(`已删除 ${res?.data?.deleted ?? 0} 条`)
    selectedIds.value = []
    reload()
  } catch (e) {
    message.error(e?.response?.data?.msg || '批量删除失败')
  }
}

const handleBatchAction = (action) => {
  showBatchMenu.value = false
  if (action === 'import') batchImport()
  else if (action === 'delete') batchDelete()
}

const viewJson = (row) => {
  currentProductId.value = row.id
  currentRawJson.value = row.prod_info_json || ''
  jsonError.value = ''
  jsonTree.value = []
  try {
    const parsed = JSON.parse(row.prod_info_json || '{}')
    jsonTree.value = buildJsonTree(parsed)
  } catch (e) {
    jsonError.value = e.message
  }
  showJsonModal.value = true
}

const copyJson = async () => {
  const text = jsonError.value ? currentRawJson.value : JSON.stringify(JSON.parse(currentRawJson.value || '{}'), null, 2)
  try {
    await navigator.clipboard.writeText(text)
    message.success('已复制')
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.left = '-9999px'
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    message.success('已复制')
  }
}

const copyJsonValue = async (val) => {
  try {
    await navigator.clipboard.writeText(val)
    message.success('已复制')
  } catch {
    message.error('复制失败')
  }
}

// ─── 表格列 ───
const columns = [
  {
    title: () => h(NCheckbox, { checked: isAllChecked.value, onUpdateChecked: toggleAll }),
    key: 'select', width: 60,
    render: row => h(NCheckbox, { checked: selectedIds.value.includes(row.id), onUpdateChecked: (checked) => toggle(row.id, checked) }),
  },
  { title: '序号', key: 'index', width: 48, align: 'center', render: (_, index) => index + 1 },
  {
    title: '来源URL', key: 'source_url', width: 200,
    ellipsis: { tooltip: { width: 'trigger' } },
  },
  {
    title: '产品URL', key: 'product_url', width: 200,
    ellipsis: { tooltip: { width: 'trigger' } },
  },
  {
    title: '标题', key: 'title', width: 180,
    ellipsis: { tooltip: { width: 'trigger' } },
  },
  {
    title: 'Vendor', key: 'vendor', width: 120,
    ellipsis: { tooltip: true },
  },
  {
    title: '类型', key: 'product_type', width: 120,
    ellipsis: { tooltip: true },
  },
  {
    title: '状态', key: 'status', width: 80, align: 'center',
    render: (row) => {
      const map = { active: 'success', draft: 'default', archived: 'warning' }
      return h(NTag, { type: map[row.status] || 'default', size: 'small', bordered: false }, () => row.status || '-')
    },
  },
  {
    title: 'JSON', key: 'prod_info_json', width: 72, align: 'center',
    render: row => h(NButton, {
      size: 'small', type: 'tertiary',
      onClick: () => viewJson(row),
    }, { default: () => '查看' }),
  },
  {
    title: '操作', key: 'actions', width: 200,
    render: row => h(NSpace, { size: 'small' }, { default: () => [
      h(NButton, { size: 'small', type: 'primary', onClick: () => importOne(row) }, { default: () => '导入' }),
      h(NPopconfirm, { onPositiveClick: () => deleteOne(row) }, {
        default: () => '确定删除该产品？',
        trigger: () => h(NButton, { size: 'small', type: 'error', quaternary: true }, { default: () => '删除' }),
      }),
    ] }),
  },
]
</script>

<style scoped>
/* ─── JSON Viewer ─── */
.json-viewer {
  font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  max-height: 55vh;
  overflow: auto;
  background: #1e1e2e;
  border-radius: 8px;
  padding: 12px 0;
}

.json-line {
  white-space: pre;
  min-height: 21px;
  transition: background 0.1s;
}

.json-line:hover {
  background: rgba(255, 255, 255, 0.04);
}

/* ─── Error state ─── */
.json-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 24px;
  color: #f38ba8;
  background: rgba(243, 139, 168, 0.08);
  border-radius: 8px;
}

.json-raw {
  margin: 12px 0 0;
  padding: 12px;
  background: #1e1e2e;
  color: #cdd6f4;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  width: 100%;
  max-height: 40vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

/* ─── Mobile ─── */
@media (max-width: 640px) {
  .json-viewer {
    font-size: 11px;
    max-height: 45vh;
  }
}
</style>
