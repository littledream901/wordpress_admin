<template>
  <CommonPage title="账号管理">
    <template #action>
      <n-button type="primary" @click="handleAdd">
        <TheIcon icon="material-symbols:add" :size="16" class="mr-5" />
        新增账号
      </n-button>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :get-data="api.getAccountList"
      :columns="columns"
    >
      <template #queryBar>
        <n-input
          v-model:value="queryItems.account_type"
          placeholder="账号类型"
          clearable
          style="width: 140px"
          @keyup.enter="$table?.handleSearch()"
        />
        <n-input
          v-model:value="queryItems.username"
          placeholder="账号搜索"
          clearable
          style="width: 200px"
          @keyup.enter="$table?.handleSearch()"
        />
        <n-select
          v-model:value="queryItems.provider_id"
          :options="providerOptions"
          placeholder="Provider"
          clearable
          style="width: 180px"
          @update:value="$table?.handleSearch()"
        />
      </template>
    </CrudTable>

    <CrudModal
      v-model:visible="modalVisible"
      :title="modalTitle"
      :loading="modalLoading"
      width="560px"
      @save="handleSave"
    >
      <n-form ref="modalFormRef" :model="modalForm" label-placement="left" :label-width="80">
        <n-form-item label="账号类型" path="account_type" :rule="{ required: true, message: '请输入账号类型' }">
          <n-input v-model:value="modalForm.account_type" placeholder="如 gmail, shopify, cloudflare 等" />
        </n-form-item>
        <n-form-item label="账号" path="username" :rule="{ required: true, message: '请输入账号' }">
          <n-input v-model:value="modalForm.username" placeholder="账号/用户名" />
        </n-form-item>
        <n-form-item label="密码" path="password" :rule="{ required: !modalForm.id, message: '请输入密码' }">
          <n-input
            v-model:value="modalForm.password"
            type="password"
            show-password-on="click"
            placeholder="密码"
          />
        </n-form-item>
        <n-form-item label="Provider" path="provider_id">
          <n-select
            v-model:value="modalForm.provider_id"
            :options="providerOptions"
            placeholder="选择关联的 Provider"
            clearable
          />
        </n-form-item>
        <n-form-item label="环境ID" path="env_id">
          <n-input-number v-model:value="modalForm.env_id" :min="0" style="width: 100%" />
        </n-form-item>
        <n-form-item label="2FA" path="two_fa">
          <n-input v-model:value="modalForm.two_fa" placeholder="两步验证密钥" />
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

import { renderIcon } from '@/utils'
import { useCRUD } from '@/composables'
import api from '@/api'
import providerApi from '@/api/configProvider'

defineOptions({ name: '账号管理' })

const $table = ref(null)
const queryItems = reactive({ account_type: '', username: '', provider_id: null })
const providerOptions = ref([])

const initForm = {
  account_type: '',
  username: '',
  password: '',
  env_id: 0,
  two_fa: '',
  remark: '',
  provider_id: null,
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
  name: '账号',
  initForm,
  doCreate: api.createAccount,
  doUpdate: api.updateAccount,
  doDelete: api.deleteAccount,
  refresh: () => $table.value?.handleSearch(),
})

const columns = [
  { title: '序号', key: 'index', width: 40, align: 'center', render: (_, index) => index + 1 },
  {
    title: '账号类型', key: 'account_type', width: 90,
    render: (row) => h(NTag, { type: 'info', size: 'small' }, { default: () => row.account_type }),
  },
  { title: '账号', key: 'username', width: 120, ellipsis: { tooltip: true } },
  {
    title: '密码', key: 'password', width: 90,
    render: (row) => h(NButton, {
      size: 'tiny', quaternary: true,
      onClick: () => { row._revealed = !row._revealed },
    }, { default: () => row._revealed ? row.password : '\u2022\u2022\u2022\u2022\u2022\u2022' }),
  },
  {
    title: 'Provider', key: 'provider_name', width: 90, ellipsis: { tooltip: true },
    render: (row) => row.provider_name
      ? h(NTag, { type: 'success', size: 'small', bordered: false }, { default: () => row.provider_name })
      : h('span', { style: { color: '#999' } }, '-'),
  },
  { title: '环境ID', key: 'env_id', width: 90, align: 'center' },
  { title: '2FA', key: 'two_fa', width: 90, ellipsis: { tooltip: true } },
  { title: '备注', key: 'remark', width: 90, ellipsis: { tooltip: true } },
  {
    title: '操作', key: 'actions', width: 140,
    render: (row) => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'tiny', onClick: () => handleEdit(row) }, { default: () => '编辑' }),
        h(NPopconfirm, { onPositiveClick: () => api.deleteAccount({ id: row.id }).then(() => $table.value?.handleSearch()) }, {
          default: () => '确定删除此账号？',
          trigger: () => h(NButton, { size: 'tiny', type: 'error' }, { default: () => '删除' }),
        }),
      ],
    }),
  },
]

onMounted(async () => {
  try {
    const r = await providerApi.getProviders({})
    providerOptions.value = (r.data || []).map(p => ({
      value: p.id,
      label: `${p.provider_name} (${p.provider_type})`,
    }))
  } catch { /* ignore */ }
  $table.value?.handleSearch()
})
</script>
