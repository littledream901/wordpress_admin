<template>
  <CommonPage title="Gmail 管理">
    <template #action>
      <n-space>
        <n-button v-permission="'post/api/v1/gmail/create'" type="primary" @click="handleAdd">新增 Gmail</n-button>
        <input ref="fileInputEl" type="file" accept=".xlsx,.csv" style="display:none" @change="handleFileChange" />
        <n-button v-permission="'post/api/v1/gmail/batch-create'" @click="fileInputEl.click()" :loading="uploadLoading">导入 Excel</n-button>
      </n-space>
    </template>

    <CrudTable ref="$table" v-model:query-items="queryItems" :get-data="api.getList" :columns="columns" :pagination="pagination" @on-checked="onCheckedChange">
      <template #queryBar>
        <n-input v-model:value="queryItems.username" placeholder="Username 搜索" clearable style="width: 240px" @keyup.enter="$table?.handleSearch()" />
      </template>
      <template #queryBarActions>
        <template v-if="checkedRowKeys.length">
          <n-divider vertical />
          <span style="white-space: nowrap; font-size: 14px">已选 {{ checkedRowKeys.length }} 项</span>
          <n-button v-permission="'post/api/v1/gmail/batch-delete'" type="error" @click="showBatchDeleteConfirm = true">批量删除</n-button>
          <n-button @click="checkedRowKeys = []">取消选择</n-button>
        </template>
      </template>
    </CrudTable>
    <CrudModal v-model:visible="modalVisible" :title="modalTitle" :loading="modalLoading" width="720px" @save="handleSave">
      <n-form ref="modalFormRef" :model="modalForm" label-placement="left" :label-width="100">
        <n-grid :cols="2" :x-gap="16">
          <n-gi :span="2"><n-text depth="3" style="font-size:13px">必填信息</n-text></n-gi>
          <n-gi><n-form-item label="Username" path="username"><n-input v-model:value="modalForm.username" placeholder="必填" /></n-form-item></n-gi>
          <n-gi><n-form-item label="Password"><n-input v-model:value="modalForm.password" /></n-form-item></n-gi>
          <n-gi><n-form-item label="2FA Key"><n-input v-model:value="modalForm.two_fa_key" /></n-form-item></n-gi>
          <n-gi><n-form-item label="2FA Link"><n-input v-model:value="modalForm.link_to_generate_login_code" /></n-form-item></n-gi>
          <n-gi><n-form-item label="Recovery Email"><n-input v-model:value="modalForm.recovery_email" /></n-form-item></n-gi>
          <n-gi><n-form-item label="健康状态">
            <n-select v-model:value="modalForm.status" :options="[{ label: '正常', value: '正常' }, { label: '不正常', value: '不正常' }]" />
          </n-form-item></n-gi>
        </n-grid>

        <n-collapse style="margin-top:12px">
          <n-collapse-item title="个人信息（可选）" name="info">
            <n-grid :cols="2" :x-gap="16">
              <n-gi><n-form-item label="Last name"><n-input v-model:value="modalForm.last_name" /></n-form-item></n-gi>
              <n-gi><n-form-item label="First name"><n-input v-model:value="modalForm.first_name" /></n-form-item></n-gi>
              <n-gi><n-form-item label="Full name"><n-input v-model:value="modalForm.full_name" /></n-form-item></n-gi>
              <n-gi><n-form-item label="Phone"><n-input v-model:value="modalForm.phone" /></n-form-item></n-gi>
              <n-gi><n-form-item label="Country"><n-input v-model:value="modalForm.country" /></n-form-item></n-gi>
              <n-gi><n-form-item label="Province/State"><n-input v-model:value="modalForm.province_state" /></n-form-item></n-gi>
              <n-gi><n-form-item label="City"><n-input v-model:value="modalForm.city" /></n-form-item></n-gi>
              <n-gi><n-form-item label="Zip code"><n-input v-model:value="modalForm.zip_code" /></n-form-item></n-gi>
              <n-gi :span="2"><n-form-item label="Shipping address 1"><n-input v-model:value="modalForm.shipping_address_1" /></n-form-item></n-gi>
              <n-gi :span="2"><n-form-item label="Shipping address 2"><n-input v-model:value="modalForm.shipping_address_2" /></n-form-item></n-gi>
            </n-grid>
          </n-collapse-item>
        </n-collapse>
      </n-form>
    </CrudModal>

    <n-modal v-model:show="showBatchDeleteConfirm" preset="dialog" title="确认批量删除"
      positive-text="确认删除" :loading="batchDeleteLoading"
      @positive-click="handleBatchDelete"
      @negative-click="showBatchDeleteConfirm = false">
      确定要删除 <b>{{ checkedRowKeys.length }}</b> 个 Gmail 账号吗？此操作不可撤销。
    </n-modal>
  </CommonPage>
</template>
<script setup>
import { h, reactive, ref } from 'vue'
import { NButton, NTag, NSelect, NSpace, NGrid, NGi, NCollapse, NCollapseItem, NText, NIcon, NPopconfirm, NDivider, useMessage } from 'naive-ui'
import { Copy } from '@vicons/carbon'
import api from '@/api/gmail'
import importJobApi from '@/api/importJob'
import { useCRUD } from '@/composables'

const message = useMessage()
const queryItems = reactive({ username: '' })
const pagination = reactive({ page: 1, pageSize: 10, showSizePicker: true, pageSizes: [10, 20, 50] })
const $table = ref(null)
const uploadLoading = ref(false)
const fileInputEl = ref(null)
const checkedRowKeys = ref([])
const showBatchDeleteConfirm = ref(false)
const batchDeleteLoading = ref(false)

const { modalVisible, modalTitle, modalLoading, handleAdd, handleEdit, handleSave, modalForm, modalFormRef } = useCRUD({
  name: 'Gmail账号',
  initForm: { last_name:'', first_name:'', full_name:'', zip_code:'', shipping_address_1:'', shipping_address_2:'', country:'', province_state:'', city:'', phone:'', username:'', password:'', two_fa_key:'', link_to_generate_login_code:'', recovery_email:'', status:'正常' },
  doCreate: api.create,
  doUpdate: api.update,
  doDelete: async () => {},
  refresh: () => $table.value?.handleSearch(),
})

function formatAddress(row) {
  const parts = [row.shipping_address_1, row.shipping_address_2, row.city, row.province_state, row.zip_code, row.country]
  const addr = parts.filter(Boolean).join(', ')
  return row.country ? `${addr}` : addr
}

const copyIcon = () => h(NIcon, { size: 16 }, { default: () => h(Copy) })

async function copyText(row, field, label) {
  try {
    await navigator.clipboard.writeText(row[field] || '')
    message.success(`${label} 已复制`)
  } catch {
    message.error('复制失败')
  }
}

const columns = [
  { type: 'selection', width: 40 },
  { title: '序号', key: 'index', width: 50, align: 'center', render: (_, index) => index + 1 },
  {
    title: 'Username', key: 'username', width: 280,
    render: (row) => h(NSpace, { size: 'small' }, {
      default: () => [
        h('span', row.username),
        h(NButton, { size: 'tiny', quaternary: true, onClick: () => copyText(row, 'username', 'Username') }, { icon: copyIcon }),
      ],
    }),
  },
  {
    title: 'Password', key: 'password', width: 140,
    render: (row) => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'tiny', quaternary: true, onClick: () => { row._revealed = !row._revealed } },
          { default: () => row._revealed ? row.password : '••••••' }),
        h(NButton, { size: 'tiny', quaternary: true, onClick: () => copyText(row, 'password', 'Password') }, { icon: copyIcon }),
      ],
    }),
  },
  {
    title: 'Address', key: 'address', width: 280, ellipsis: { tooltip: true },
    render: (row) => formatAddress(row),
  },
  { title: '2FA Link', key: 'link_to_generate_login_code', width: 140, ellipsis: { tooltip: true } },
  { title: 'Recovery Email', key: 'recovery_email', width: 160, ellipsis: { tooltip: true } },
  {
    title: '健康状态', key: 'status', width: 85,
    render: row => h(NTag, { type: row.status === '正常' ? 'success' : row.status === '不正常' ? 'error' : 'default', size: 'small' }, { default: () => row.status || '-' }),
  },
  { title: '分配站点', key: 'assigned_site_domain', width: 140, ellipsis: { tooltip: true } },
  {
    title: '操作', key: 'actions', width: 210,
    render: (row) => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'tiny', onClick: () => handleEdit(row) }, { default: () => '编辑' }),
        h(NButton, {
          size: 'tiny',
          type: row.status === '不正常' ? 'success' : 'warning',
          onClick: () => toggleHealth(row),
        }, { default: () => row.status === '不正常' ? '设为正常' : '设为不正常' }),
        h(NPopconfirm, { onPositiveClick: () => handleDeleteSingle(row.id) }, {
          default: () => '确定删除此账号？',
          trigger: () => h(NButton, { size: 'tiny', type: 'error' }, { default: () => '删除' }),
        }),
      ],
    }),
  },
]

async function toggleHealth(row) {
  const newStatus = row.status === '不正常' ? '正常' : '不正常'
  try {
    await api.setHealthStatus({ id: row.id, status: newStatus })
    message.success(`已设为${newStatus}`)
    $table.value?.handleSearch()
  } catch (e) {
    message.error(e?.response?.data?.msg || '操作失败')
  }
}

function onCheckedChange(keys) {
  checkedRowKeys.value = keys
}

async function handleDeleteSingle(id) {
  try {
    await api.batchDelete([id])
    message.success('删除成功')
    checkedRowKeys.value = checkedRowKeys.value.filter(k => k !== id)
    $table.value?.handleSearch()
  } catch (e) {
    message.error(e?.response?.data?.msg || '删除失败')
  }
}

async function handleBatchDelete() {
  if (!checkedRowKeys.value.length) return
  batchDeleteLoading.value = true
  try {
    await api.batchDelete(checkedRowKeys.value)
    message.success(`已删除 ${checkedRowKeys.value.length} 条`)
    checkedRowKeys.value = []
    showBatchDeleteConfirm.value = false
    $table.value?.handleSearch()
  } catch (e) {
    message.error(e?.response?.data?.msg || '批量删除失败')
    throw e
  } finally {
    batchDeleteLoading.value = false
  }
}

async function handleFileChange(e) {
  const file = e.target.files[0]
  if (!file) return
  uploadLoading.value = true
  try {
    const formData = new FormData()
    formData.append('file', file)
    const res = await importJobApi.upload('gmail', formData)
    const data = res?.data ?? {}
    message.success(`导入完成：成功 ${data.success ?? 0}，失败 ${data.fail ?? 0}`)
    $table.value?.handleSearch()
  } catch (err) {
    message.error(err?.response?.data?.msg || '导入失败')
  } finally {
    uploadLoading.value = false
    e.target.value = ''
  }
}
</script>
