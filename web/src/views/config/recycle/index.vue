<template>
  <CommonPage title="回收站">
    <template #action>
      <n-button v-permission="'post/api/v1/recycle-bin/empty'" type="error" secondary @click="handleEmpty">
        <TheIcon icon="mdi:delete-sweep" :size="16" class="mr-5" />
        清空当前分类
      </n-button>
    </template>

    <n-card size="small" mb-16>
      <n-space align="center">
        <span style="font-weight: 500">数据类型：</span>
        <n-radio-group v-model:value="currentType" name="recycle-type" @update:value="onTypeChange">
          <n-radio-button v-for="t in typeOptions" :key="t.value" :value="t.value" :label="t.label" />
        </n-radio-group>
      </n-space>
    </n-card>

    <CrudTable
      ref="tableRef"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="fetchData"
      :extra-params="extraParams"
      remote
    >
      <template #queryBar>
        <n-input v-model:value="queryItems.keyword" placeholder="搜索关键字" clearable style="width: 220px" />
      </template>
    </CrudTable>

    <!-- 详情弹窗 -->
    <n-modal v-model:show="showDetail" preset="card" title="数据详情" style="max-width: 960px">
      <div v-for="group in detailGroups" :key="group.title" class="detail-group">
        <n-card :title="group.title" size="small">
          <template v-if="group.isLog">
            <n-input type="textarea" :value="group.value || ''" :rows="12" readonly />
          </template>
          <template v-else>
            <n-descriptions label-placement="left" bordered :column="2" size="small">
              <n-descriptions-item v-for="item in group.fields" :key="item.key" :label="item.label">
                <template v-if="isJsonString(item.value)">
                  <pre class="json-preview">{{ formatJson(item.value) }}</pre>
                </template>
                <template v-else>
                  {{ item.value ?? '-' }}
                </template>
              </n-descriptions-item>
            </n-descriptions>
          </template>
        </n-card>
      </div>
    </n-modal>
  </CommonPage>
</template>

<script setup>
import { h, ref, reactive, computed, nextTick } from 'vue'
import {
  NButton, NCard, NDescriptions, NDescriptionsItem,
  NInput, NModal, NPopconfirm, NRadioButton, NRadioGroup,
  NSpace, useMessage, useDialog,
} from 'naive-ui'

import CommonPage from '@/components/page/CommonPage.vue'
import CrudTable from '@/components/table/CrudTable.vue'
import TheIcon from '@/components/icon/TheIcon.vue'
import api from '@/api/recycleBin'

defineOptions({ name: '回收站' })

const message = useMessage()
const dialog = useDialog()
const tableRef = ref(null)

const typeOptions = [
  { value: 'site', label: '站点' },
  { value: 'gmail', label: 'Gmail' },
  { value: 'account', label: '账号' },
  { value: 'provider', label: '配置' },
  { value: 'ads', label: 'ADS' },
]

// 详情字段分组定义
const FIELD_GROUPS = {
  site: [
    { title: '基础信息', keys: ['id', 'domain', 'server_ip', 'status', 'dept_id', 'create_by', 'created_at', 'updated_at'] },
    { title: '站点配置', keys: ['login_url', 'woo_ck', 'woo_cs', 'ctx_refresh_url', 'feed_link'] },
    { title: '运行状态', keys: ['cloudflare_status', 'dynadot_status', 'onepanel_status', 'hub_status', 'hub_env_id', 'hub_env_name', 'hub_account_id', 'pipeline_status', 'woo_product_count', 'woo_import_status', 'gmc_status'] },
    { title: '流水线日志', logKey: 'pipeline_log' },
    { title: 'GMC 数据', logKey: 'gmc_data' },
  ],
  gmail: [
    { title: '基本信息', keys: ['id', 'username', 'password', 'status', 'assigned_site_id', 'assigned_site_domain', 'created_at', 'updated_at'] },
    { title: '个人信息', keys: ['last_name', 'first_name', 'full_name', 'phone', 'recovery_email'] },
    { title: '地址信息', keys: ['country', 'province_state', 'city', 'zip_code', 'shipping_address_1', 'shipping_address_2'] },
    { title: '安全信息', keys: ['two_fa_key', 'two_fa_code'] },
  ],
  account: [
    { title: '基本信息', keys: ['id', 'account_type', 'username', 'password', 'env_id', 'provider_id', 'created_at', 'updated_at'] },
    { title: '其他', keys: ['two_fa', 'remark'] },
  ],
  provider: [
    { title: '基本信息', keys: ['id', 'provider_name', 'provider_type', 'is_default', 'status', 'priority', 'created_at', 'updated_at'] },
    { title: '其他', keys: ['description', 'remark', 'api_version', 'base_url', 'error_message'] },
  ],
  ads: [
    { title: '基本信息', keys: ['id', 'ads_env_id', 'domain', 'status', 'remark', 'created_at', 'updated_at', 'deleted_at'] },
  ],
}

const currentType = ref('site')
const queryItems = reactive({ keyword: '' })
const extraParams = reactive({ type: currentType.value })

// 详情弹窗
const showDetail = ref(false)
const detailGroups = ref([])

const columns = computed(() => {
  const base = [
    { title: 'ID', key: 'id', width: 70 },
    { title: '摘要', key: 'summary', width: 250, ellipsis: { tooltip: true } },
  ]
  // 站点 tab 增加 IP 和环境 ID 列
  if (currentType.value === 'site') {
    base.push(
      { title: '服务器IP', key: 'server_ip', width: 140 },
      { title: '环境ID', key: 'hub_env_id', width: 120 },
    )
  }
  base.push(
    {
      title: '删除时间', key: 'deleted_at', width: 180,
      render(row) { return row.deleted_at || '-' },
    },
    { title: '原创建时间', key: 'created_at', width: 180 },
    {
      title: '操作', key: 'actions', width: 260,
      render(row) {
        return h(NSpace, { size: 'small' }, () => [
          h(NButton, {
            size: 'tiny', type: 'default', quaternary: true,
            onClick: () => handleDetail(row),
          }, () => '详情'),
          h(NButton, {
            size: 'tiny', type: 'primary', secondary: true,
            onClick: () => handleRestore(row),
          }, () => '恢复'),
          h(
            NPopconfirm,
            {
              onPositiveClick: () => handlePermanentDelete(row),
            },
            {
              trigger: () => h(NButton, { size: 'tiny', type: 'error', quaternary: true }, () => '彻底删除'),
              default: () => '确定要彻底删除该数据吗？此操作不可撤销。',
            },
          ),
        ])
      },
    },
  )
  return base
})

async function fetchData(params) {
  const { data, total } = await api.getList({
    type: currentType.value,
    page: params.page,
    page_size: params.page_size,
    keyword: params.keyword || '',
  })
  return { data: data || [], total: total || 0 }
}

function onTypeChange() {
  extraParams.type = currentType.value
  queryItems.keyword = ''
  nextTick(() => tableRef.value?.handleSearch())
}

async function handleRestore(row) {
  try {
    await api.restore({ type: currentType.value, id: row.id })
    message.success('已恢复')
  } catch {
    message.error('恢复失败')
  }
  tableRef.value?.handleSearch()
}

async function handlePermanentDelete(row) {
  try {
    await api.permanentDelete({ type: currentType.value, id: row.id })
    message.success('已彻底删除')
  } catch {
    message.error('删除失败')
  }
  tableRef.value?.handleSearch()
}

function handleEmpty() {
  const typeLabel = typeOptions.find(t => t.value === currentType.value)?.label || currentType.value
  dialog.warning({
    title: '清空回收站',
    content: `确定要清空「${typeLabel}」回收站中的所有数据吗？此操作不可撤销。`,
    positiveText: '确定清空',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        const r = await api.empty({ type: currentType.value })
        message.success(r.msg || '已清空')
      } catch {
        message.error('清空失败')
      }
      tableRef.value?.handleSearch()
    },
  })
}

function handleDetail(row) {
  const groups = FIELD_GROUPS[currentType.value] || []
  detailGroups.value = groups.map(g => {
    if (g.logKey) {
      return { title: g.title, isLog: true, value: row[g.logKey] }
    }
    return {
      title: g.title,
      fields: (g.keys || [])
        .filter(k => row[k] !== undefined)
        .map(k => ({ key: k, label: fieldLabel(k), value: row[k] })),
    }
  }).filter(g => g.isLog || (g.fields && g.fields.length))
  showDetail.value = true
}

const LABEL_MAP = {
  id: 'ID', domain: '域名', server_ip: '服务器IP', status: '状态',
  dept_id: '部门ID', create_by: '创建人ID', created_at: '创建时间', updated_at: '更新时间',
  login_url: '登录地址', woo_ck: 'Woo CK', woo_cs: 'Woo CS',
  ctx_refresh_url: 'CTX Refresh URL', feed_link: 'Feed链接',
  cloudflare_status: 'Cloudflare状态', dynadot_status: 'Dynadot状态', onepanel_status: '1Panel状态',
  hub_status: 'Hub状态', hub_env_id: 'Hub环境ID', hub_env_name: 'Hub环境名称',
  hub_account_id: 'Hub账号ID', pipeline_status: '流水线状态',
  pipeline_log: '流水线日志', gmc_data: 'GMC数据', gmc_status: 'GMC状态',
  product_count: '商品数量', woo_import_status: 'Woo导入状态',
  username: '用户名', password: '密码', assigned_site_id: '分配站点ID', assigned_site_domain: '分配站点域名',
  last_name: '姓', first_name: '名', full_name: '全名', phone: '电话', recovery_email: '恢复邮箱',
  country: '国家', province_state: '省/州', city: '城市', zip_code: '邮编',
  shipping_address_1: '地址1', shipping_address_2: '地址2',
  two_fa_key: '2FA密钥', two_fa_code: '2FA验证码',
  account_type: '账号类型', env_id: '环境ID', provider_id: 'Provider ID', two_fa: '2FA', remark: '备注',
  provider_name: 'Provider名称', provider_type: 'Provider类型', is_default: '默认', priority: '优先级',
  description: '描述', base_url: '基础URL', api_version: 'API版本', error_message: '错误信息',
  ads_env_id: 'ADS环境ID', domain: '域名', deleted_at: '删除时间',
}

function fieldLabel(key) {
  return LABEL_MAP[key] || key
}

function isJsonString(val) {
  if (typeof val !== 'string' || val.length < 2) return false
  return (val.startsWith('{') && val.endsWith('}')) || (val.startsWith('[') && val.endsWith(']'))
}

function formatJson(val) {
  try {
    return JSON.stringify(JSON.parse(val), null, 2)
  } catch {
    return val
  }
}
</script>

<style scoped>
.detail-group + .detail-group {
  margin-top: 16px;
}

.json-preview {
  margin: 0;
  padding: 8px 12px;
  background: #f6f8fa;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
