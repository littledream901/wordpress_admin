<template>
  <CommonPage title="ADS管理">
    <template #action>
      <n-button type="primary" @click="handleAdd">
        <TheIcon icon="material-symbols:add" :size="16" class="mr-5" />
        新增ADS
      </n-button>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :get-data="api.getAdsEnvList"
      :columns="columns"
    >
      <template #queryBar>
        <n-input
          v-model:value="queryItems.ads_env_id"
          placeholder="环境ID"
          clearable
          style="width: 160px"
          @keyup.enter="$table?.handleSearch()"
        />
        <n-input
          v-model:value="queryItems.domain"
          placeholder="域名搜索"
          clearable
          style="width: 200px"
          @keyup.enter="$table?.handleSearch()"
        />
        <n-select
          v-model:value="queryItems.status"
          :options="statusOptions"
          placeholder="状态"
          clearable
          style="width: 120px"
          @update:value="$table?.handleSearch()"
        />
      </template>
    </CrudTable>

    <CrudModal
      v-model:visible="modalVisible"
      :title="modalTitle"
      :loading="modalLoading"
      width="520px"
      @save="handleSave"
    >
      <n-form ref="modalFormRef" :model="modalForm" label-placement="left" :label-width="80">
        <n-form-item label="环境ID" path="ads_env_id" :rule="{ required: true, message: '请输入ADS环境ID' }">
          <n-input v-model:value="modalForm.ads_env_id" placeholder="ADS 浏览器环境 ID" />
        </n-form-item>
        <n-form-item label="ADS名称" path="domain">
          <n-input v-model:value="modalForm.domain" placeholder="ADS环境名称（便于搜索）" />
        </n-form-item>
        <n-form-item label="关联站点" path="site_ids">
          <n-select
            v-model:value="modalForm.site_ids"
            :options="siteOptions"
            placeholder="选择关联站点（可多选）"
            clearable
            filterable
            multiple
          />
        </n-form-item>
        <n-form-item label="状态" path="status">
          <n-select
            v-model:value="modalForm.status"
            :options="statusOptions"
            placeholder="选择状态"
          />
        </n-form-item>
        <n-form-item label="备注" path="remark">
          <n-input v-model:value="modalForm.remark" type="textarea" placeholder="备注信息" />
        </n-form-item>
      </n-form>
    </CrudModal>
  </CommonPage>
</template>

<script setup>
import { h, ref, reactive, onMounted } from 'vue'
import { NButton, NTag, NPopconfirm, NSpace, NSelect } from 'naive-ui'

import CommonPage from '@/components/page/CommonPage.vue'
import CrudTable from '@/components/table/CrudTable.vue'
import CrudModal from '@/components/table/CrudModal.vue'
import TheIcon from '@/components/icon/TheIcon.vue'

import { useCRUD } from '@/composables'
import api from '@/api/site-pipeline'

defineOptions({ name: 'ADS管理' })

const $table = ref(null)
const queryItems = reactive({ ads_env_id: '', domain: '', status: '' })
const siteOptions = ref([])

const statusOptions = [
  { value: '正常', label: '正常' },
  { value: '异常', label: '异常' },
  { value: '离线', label: '离线' },
]

const initForm = {
  ads_env_id: '',
  domain: '',
  site_ids: [],
  status: '正常',
  remark: '',
}

const {
  modalVisible,
  modalTitle,
  modalLoading,
  handleAdd,
  handleEdit,
  handleSave,
  modalForm,
  modalFormRef,
} = useCRUD({
  name: 'ADS环境',
  initForm,
  doCreate: (data) => api.createAdsEnv(data),
  doUpdate: (data) => api.updateAdsEnv(data),
  doDelete: (id) => api.deleteAdsEnv(id),
  refresh: () => $table.value?.handleSearch(),
})

const addingSiteRowId = ref(null)
const addingSiteValue = ref(null)

function startAdding(rowId) {
  addingSiteRowId.value = rowId
  addingSiteValue.value = null
}

function cancelAdding() {
  addingSiteRowId.value = null
  addingSiteValue.value = null
}

const columns = [
  { title: '序号', key: 'index', width: 50, align: 'center', render: (_, index) => index + 1 },
  { title: '环境ID', key: 'ads_env_id', width: 160, ellipsis: { tooltip: true } },
  { title: 'ADS名称', key: 'domain', width: 160, ellipsis: { tooltip: true } },
  {
    title: '关联站点', key: 'site_domains', width: 240,
    render: (row) => {
      const domains = row.site_domains || []
      const isAdding = addingSiteRowId.value === row.id
      const children = []

      // 已有站点 Tag（可关闭）
      for (const d of domains) {
        children.push(
          h('div', { style: 'margin-bottom:2px' }, [
            h(NTag, {
              type: 'info', size: 'tiny', bordered: false, closable: true,
              onClose: () => {
                const idx = (row.site_domains || []).indexOf(d)
                const sid = (row.site_ids || [])[idx]
                if (sid != null) {
                  api.adsRemoveSite(row.id, sid).then(() => $table.value?.handleSearch())
                }
              },
            }, { default: () => d }),
          ])
        )
      }

      // 添加按钮 / 行内选择器
      if (isAdding) {
        children.push(
          h('div', { style: 'display:flex;gap:4px;margin-top:2px' }, [
            h(NSelect, {
              value: addingSiteValue.value,
              'onUpdate:value': (v) => { addingSiteValue.value = v },
              options: siteOptions.value.filter(o => !(row.site_ids || []).includes(o.value)),
              placeholder: '选择站点',
              size: 'tiny',
              style: 'width:140px',
              filterable: true,
              clearable: true,
            }),
            h(NButton, { size: 'tiny', type: 'primary', onClick: () => {
              if (addingSiteValue.value) {
                api.adsAddSite(row.id, addingSiteValue.value).then(() => {
                  cancelAdding()
                  $table.value?.handleSearch()
                })
              }
            }}, { default: () => '确认' }),
            h(NButton, { size: 'tiny', onClick: cancelAdding }, { default: () => '取消' }),
          ])
        )
      } else {
        const remaining = siteOptions.value.filter(o => !(row.site_ids || []).includes(o.value))
        if (remaining.length > 0) {
          children.push(
            h(NButton, { size: 'tiny', quaternary: true, style: 'margin-top:2px',
              onClick: () => startAdding(row.id),
            }, { default: () => '+ 关联站点' })
          )
        }
      }

      if (children.length === 0) {
        return h('span', { style: { color: '#999' } }, '-')
      }
      return h('div', {}, children)
    },
  },
  {
    title: '状态', key: 'status', width: 80, align: 'center',
    render: (row) => {
      const typeMap = { '正常': 'success', '异常': 'warning', '离线': 'default' }
      return h(NTag, { type: typeMap[row.status] || 'default', size: 'small' }, { default: () => row.status })
    },
  },
  { title: '备注', key: 'remark', width: 120, ellipsis: { tooltip: true } },
  {
    title: '操作', key: 'actions', width: 140,
    render: (row) => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'tiny', onClick: () => handleEdit(row) }, { default: () => '编辑' }),
        h(NPopconfirm, { onPositiveClick: () => api.deleteAdsEnv(row).then(() => $table.value?.handleSearch()) }, {
          default: () => '确定删除此环境？',
          trigger: () => h(NButton, { size: 'tiny', type: 'error' }, { default: () => '删除' }),
        }),
      ],
    }),
  },
]

onMounted(async () => {
  try {
    const r = await api.getSiteList({ page: 1, page_size: 9999 })
    siteOptions.value = (r.data || []).map(s => ({
      value: s.id,
      label: s.domain,
    }))
  } catch { /* ignore */ }
  $table.value?.handleSearch()
})
</script>
