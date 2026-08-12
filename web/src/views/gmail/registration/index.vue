<template>
  <CommonPage title="Gmail 企业邮箱注册">
    <template #action>
      <n-space>
        <n-button v-permission="'post/api/v1/gmail/registration/create'" type="primary" @click="handleAdd">
          新增注册
        </n-button>
        <n-button
          v-permission="'post/api/v1/gmail/registration/batch-fetch'"
          type="warning"
          :loading="batchFetchLoading"
          @click="handleBatchFetch"
        >
          批量获取
        </n-button>
      </n-space>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :get-data="api.regGetList"
      :columns="columns"
      :pagination="pagination"
      @on-checked="onCheckedChange"
    >
      <template #queryBar>
        <n-input
          v-model:value="queryItems.alias"
          placeholder="别名搜索"
          clearable
          style="width: 180px"
          @keyup.enter="$table?.handleSearch()"
        />
        <n-input
          v-model:value="queryItems.domain"
          placeholder="站点域名搜索"
          clearable
          style="width: 180px"
          @keyup.enter="$table?.handleSearch()"
        />
        <n-select
          v-model:value="queryItems.registration_status"
          placeholder="注册状态"
          clearable
          style="width: 160px"
          :options="statusOptions"
          @update:value="$table?.handleSearch()"
        />
        <n-input
          v-model:value="queryItems.outlook_account_username"
          placeholder="Outlook 邮箱搜索"
          clearable
          style="width: 190px"
          @keyup.enter="$table?.handleSearch()"
        />
        <n-select
          v-model:value="queryItems.outlook_assigned"
          placeholder="Outlook 分配情况"
          clearable
          style="width: 170px"
          :options="outlookAssignedOptions"
          @update:value="$table?.handleSearch()"
        />
      </template>
      <template #queryBarActions>
        <template v-if="checkedRowKeys.length">
          <n-divider vertical />
          <span style="white-space: nowrap; font-size: 14px">已选 {{ checkedRowKeys.length }} 项</span>
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
              <n-button
                v-permission="'post/api/v1/gmail/registration/batch-get-phone'"
                @click="showBatchMenu = false; handleBatchOp('getPhone')"
                :loading="batchLoading === 'getPhone'"
                style="justify-content: flex-start"
              >
                <template #icon>
                  <TheIcon icon="mdi:cellphone" :size="18" />
                </template>
                批量获取号码
              </n-button>
              <n-button
                v-permission="'post/api/v1/gmail/registration/batch-wait-sms'"
                @click="showBatchMenu = false; handleBatchOp('waitSms')"
                :loading="batchLoading === 'waitSms'"
                style="justify-content: flex-start"
              >
                <template #icon>
                  <TheIcon icon="mdi:message-processing-outline" :size="18" />
                </template>
                批量等待短信
              </n-button>
              <n-button
                v-permission="'post/api/v1/gmail/registration/batch-confirm-sms'"
                @click="showBatchMenu = false; handleBatchOp('confirmSms')"
                :loading="batchLoading === 'confirmSms'"
                style="justify-content: flex-start"
              >
                <template #icon>
                  <TheIcon icon="mdi:check-circle-outline" :size="18" />
                </template>
                批量确认完成
              </n-button>
              <n-divider style="margin: 2px 0" />
              <n-button
                v-permission="'post/api/v1/gmail/registration/batch-assign-outlook'"
                @click="showBatchMenu = false; showBatchAssignOutlookModal = true"
                style="justify-content: flex-start"
              >
                <template #icon>
                  <TheIcon icon="mdi:email-multiple-outline" :size="18" />
                </template>
                批量分配 Outlook
              </n-button>
              <n-button
                v-permission="'post/api/v1/gmail/registration/batch-delete'"
                @click="showBatchMenu = false; showBatchDeleteConfirm = true"
                style="justify-content: flex-start"
              >
                <template #icon>
                  <TheIcon icon="mdi:delete-outline" :size="18" />
                </template>
                批量删除
              </n-button>
            </n-button-group>
          </n-popover>
          <n-button @click="checkedRowKeys = []">取消选择</n-button>
        </template>
      </template>
    </CrudTable>

    <!-- 新增/编辑弹窗 -->
    <CrudModal
      v-model:visible="modalVisible"
      :title="modalTitle"
      :loading="modalLoading"
      @save="handleSave"
    >
      <n-form ref="modalFormRef" :model="modalForm" label-placement="left" :label-width="120">
        <n-grid :cols="2" :x-gap="16">
          <n-gi>
            <n-form-item label="别名" path="alias">
              <n-input v-model:value="modalForm.alias" placeholder="Gmail 邮箱前缀" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="站点域名" path="domain">
              <n-input v-model:value="modalForm.domain" placeholder="example.com" />
            </n-form-item>
          </n-gi>
          <n-gi :span="2">
            <n-form-item label="Outlook 邮箱">
              <n-select
                v-model:value="modalForm.outlook_account_id"
                placeholder="选择 Outlook 邮箱（分配后自动同步身份信息）"
                clearable
                filterable
                :loading="outlookLoading"
                :options="outlookOptions"
                @focus="loadOutlookOptions"
              />
            </n-form-item>
          </n-gi>
          <n-gi :span="2">
            <n-alert type="info" :bordered="false" style="margin-bottom: 8px">
              姓名、密码、地址、电话由所选 Outlook 邮箱同步填充，无需手动录入。
            </n-alert>
          </n-gi>
          <n-gi :span="2"><n-divider style="margin: 4px 0">身份信息（来自 Outlook，只读）</n-divider></n-gi>
          <n-gi>
            <n-form-item label="姓名">
                <n-input v-model:value="modalForm.full_name" readonly placeholder="由 Outlook 同步" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="密码">
              <n-input v-model:value="modalForm.password" readonly placeholder="由 Outlook 同步" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="名">
              <n-input v-model:value="modalForm.first_name" readonly placeholder="由 Outlook 同步" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="姓">
              <n-input v-model:value="modalForm.last_name" readonly placeholder="由 Outlook 同步" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="国家">
              <n-input v-model:value="modalForm.country" readonly placeholder="由 Outlook 同步" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="省/州">
              <n-input v-model:value="modalForm.province_state" readonly placeholder="由 Outlook 同步" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="城市">
              <n-input v-model:value="modalForm.city" readonly placeholder="由 Outlook 同步" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="邮编">
              <n-input v-model:value="modalForm.zip_code" readonly placeholder="由 Outlook 同步" />
            </n-form-item>
          </n-gi>
          <n-gi :span="2">
            <n-form-item label="地址1">
              <n-input v-model:value="modalForm.shipping_address_1" readonly placeholder="由 Outlook 同步" />
            </n-form-item>
          </n-gi>
          <n-gi :span="2">
            <n-form-item label="地址2">
              <n-input v-model:value="modalForm.shipping_address_2" readonly placeholder="由 Outlook 同步" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="电话">
              <n-input v-model:value="modalForm.phone" readonly placeholder="由 Outlook 同步" />
            </n-form-item>
          </n-gi>
          <n-gi :span="2">
            <n-form-item label="转发目标邮箱">
              <n-input v-model:value="modalForm.forward_to" placeholder="ImprovMX 转发接收邮箱（默认使用恢复邮箱）" />
            </n-form-item>
          </n-gi>
          <n-gi :span="2"><n-text depth="3" style="font-size:13px">注册结果信息</n-text></n-gi>
          <n-gi>
            <n-form-item label="注册 Gmail">
              <n-input v-model:value="modalForm.registration_email" placeholder="" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="恢复邮箱">
              <n-input v-model:value="modalForm.recovery_email" disabled />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="注册状态">
              <n-select v-model:value="modalForm.registration_status" :options="statusOptions" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="环境 ID">
              <n-input v-model:value="modalForm.env_id" disabled />
            </n-form-item>
          </n-gi>
        </n-grid>
      </n-form>
    </CrudModal>

    <!-- 操作确认弹窗 -->
    <n-modal
      v-model:show="showActionModal"
      preset="dialog"
      :title="actionModalTitle"
      positive-text="执行"
      :loading="actionModalLoading"
      @positive-click="confirmAction"
      @negative-click="showActionModal = false"
    >
      <p v-if="actionType === 'getPhone'">
        <n-form ref="actionFormRef" :model="actionForm" label-placement="left" :label-width="100">
          <n-form-item label="国家 ID">
            <n-input-number v-model:value="actionForm.country_id" :min="0" placeholder="0=随机" />
          </n-form-item>
          <n-form-item label="服务 ID">
            <n-input-number v-model:value="actionForm.application_id" :min="0" placeholder="Google" />
          </n-form-item>
          <n-form-item label="最高价格(分)">
            <n-input-number v-model:value="actionForm.max_price" :min="0" placeholder="不限" />
          </n-form-item>
        </n-form>
      </p>
      <p v-else-if="actionType === 'waitSms'">等待接收验证码，超时时间 {{ actionForm.timeout }} 秒</p>
      <p v-else-if="actionType === 'confirmSms'">确认 SMS 使用完成，系统将标记为扣款。</p>
      <p v-else>确定要执行此操作吗？</p>
    </n-modal>

    <!-- 批量状态更新弹窗 -->
    <n-modal
      v-model:show="showBatchStatusModal"
      preset="dialog"
      title="批量更新状态"
      positive-text="更新"
      @positive-click="handleBatchStatusUpdate"
      @negative-click="showBatchStatusModal = false"
    >
      <n-form label-placement="left" :label-width="80">
        <n-form-item label="目标状态">
          <n-select v-model:value="batchTargetStatus" :options="statusOptions" />
        </n-form-item>
      </n-form>
    </n-modal>

    <!-- 批量删除确认 -->
    <n-modal
      v-model:show="showBatchDeleteConfirm"
      preset="dialog"
      title="确认批量删除"
      positive-text="确认删除"
      :loading="batchDeleteLoading"
      @positive-click="handleBatchDelete"
      @negative-click="showBatchDeleteConfirm = false"
    >
      确定要删除 <b>{{ checkedRowKeys.length }}</b> 条注册记录吗？
    </n-modal>

    <!-- 批量分配 Outlook -->
    <n-modal
      v-model:show="showBatchAssignOutlookModal"
      preset="dialog"
      title="批量分配 Outlook 邮箱"
      positive-text="确认分配"
      :loading="batchAssignOutlookLoading"
      @positive-click="handleBatchAssignOutlook"
      @negative-click="showBatchAssignOutlookModal = false"
    >
      <p>
        将已选 <b>{{ checkedRowKeys.length }}</b> 条注册记录，自动分配可用 Outlook 邮箱。
      </p>
      <n-text depth="3" style="font-size: 13px">
        系统将从可用 Outlook 账号池中依次分配，并同步身份信息（姓名、密码、地址、电话等）。
      </n-text>
    </n-modal>




    <!-- 详情弹窗 -->
    <n-modal
      v-model:show="showDetailModal"
      preset="card"
      title="注册记录详情"
      style="max-width:640px"
      :mask-closable="true"
      @close="showDetailModal = false"
    >
      <n-grid v-if="detailData" cols="2" x-gap="12" y-gap="8">
        <n-gi><n-text depth="3">别名</n-text></n-gi>
        <n-gi><n-text>{{ detailData.alias }}</n-text></n-gi>
        <n-gi><n-text depth="3">站点域名</n-text></n-gi>
        <n-gi><n-text>{{ detailData.domain }}</n-text></n-gi>
        <n-gi><n-text depth="3">姓名</n-text></n-gi>
        <n-gi><n-text>{{ detailData.full_name }}</n-text></n-gi>
        <n-gi><n-text depth="3">密码</n-text></n-gi>
        <n-gi>
          <n-button size="tiny" quaternary @click="navigator.clipboard.writeText(detailData.password);message.success('已复制')">
            {{ detailData.password }}
          </n-button>
        </n-gi>
        <n-gi><n-text depth="3">转发目标</n-text></n-gi>
        <n-gi><n-text>{{ detailData.forward_to || '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">辅助邮箱</n-text></n-gi>
        <n-gi><n-text>{{ detailData.recovery_email || '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">2FA Key</n-text></n-gi>
        <n-gi><n-text>{{ detailData.two_fa_key || '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">邮编</n-text></n-gi>
        <n-gi><n-text>{{ detailData.zip_code || '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">国家</n-text></n-gi>
        <n-gi><n-text>{{ detailData.country || '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">省/州</n-text></n-gi>
        <n-gi><n-text>{{ detailData.province_state || '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">城市</n-text></n-gi>
        <n-gi><n-text>{{ detailData.city || '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">地址1</n-text></n-gi>
        <n-gi><n-text>{{ detailData.shipping_address_1 || '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">地址2</n-text></n-gi>
        <n-gi><n-text>{{ detailData.shipping_address_2 || '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">电话</n-text></n-gi>
        <n-gi><n-text>{{ detailData.phone || '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">注册邮箱</n-text></n-gi>
        <n-gi><n-text>{{ detailData.registration_email || '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">ImprovMX别名ID</n-text></n-gi>
        <n-gi><n-text>{{ detailData.improvmx_alias_id || '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">环境ID</n-text></n-gi>
        <n-gi><n-text>{{ detailData.env_id || '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">环境名称</n-text></n-gi>
        <n-gi><n-text>{{ detailData.env_name || '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">SMS request_id</n-text></n-gi>
        <n-gi><n-text>{{ detailData.sms_request_id ?? '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">SMS号码</n-text></n-gi>
        <n-gi><n-text>{{ detailData.sms_phone_number || '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">SMS验证码</n-text></n-gi>
        <n-gi><n-text>{{ detailData.sms_code || '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">注册状态</n-text></n-gi>
        <n-gi>
          <n-tag :type="statusColorMap[detailData.registration_status] || 'default'" size="small">
            {{ statusLabelMap[detailData.registration_status] || detailData.registration_status }}
          </n-tag>
        </n-gi>
        <n-gi><n-text depth="3">创建时间</n-text></n-gi>
        <n-gi><n-text>{{ detailData.created_at || '-' }}</n-text></n-gi>
        <n-gi><n-text depth="3">更新时间</n-text></n-gi>
        <n-gi><n-text>{{ detailData.updated_at || '-' }}</n-text></n-gi>
      </n-grid>
    </n-modal>

  </CommonPage>
</template>

<script setup>
import { h, reactive, ref, onMounted } from 'vue'
import {
  NButton, NButtonGroup, NTag, NSelect, NSpace, NGrid, NGi, NText, NDivider,
  NPopconfirm, NPopover, NInputNumber, NInput, NTooltip, NModal, NSwitch, NAlert, useMessage, useDialog,
} from 'naive-ui'
import TheIcon from '@/components/icon/TheIcon.vue'
import api from '@/api/gmail'
import sitePipelineApi from '@/api/site-pipeline'

const message = useMessage()
const dialog = useDialog()
const queryItems = reactive({
  alias: '',
  domain: '',
  registration_status: '',
  outlook_account_username: '',
  outlook_assigned: '',
})
const pagination = reactive({ page: 1, pageSize: 10, showSizePicker: true, pageSizes: [10, 20, 50] })
const $table = ref(null)
const checkedRowKeys = ref([])
const showBatchMenu = ref(false)
const batchLoading = ref(null)  // 当前正在执行的批量操作名
const showBatchDeleteConfirm = ref(false)
const batchDeleteLoading = ref(false)
const showBatchStatusModal = ref(false)
const batchTargetStatus = ref('completed')
const batchFetchLoading = ref(false)

// ── 详情弹窗 ──
const showDetailModal = ref(false)
const detailData = ref(null)

function handleDetail(row) {
  detailData.value = row
  showDetailModal.value = true
}

// ── Outlook 分配 ──
const showBatchAssignOutlookModal = ref(false)
const batchAssignOutlookLoading = ref(false)
const outlookOptions = ref([])
const outlookLoading = ref(false)

const outlookAssignedOptions = [
  { label: '已分配 Outlook', value: 'yes' },
  { label: '未分配 Outlook', value: 'no' },
]

async function loadOutlookOptions() {
  if (outlookLoading.value) return
  outlookLoading.value = true
  try {
    const res = await api.regAvailableOutlook({ limit: 300 })
    const list = res.data || []
    // 编辑态下当前已绑定的账号不在可用池里，需补进选项避免显示为空
    const current = modalForm.outlook_account_id
    const options = list.map((a) => ({
      label: a.full_name ? `${a.username}（${a.full_name}）` : a.username,
      value: a.id,
    }))
    if (current && !options.some((o) => o.value === current)) {
      options.unshift({
        label: modalForm.outlook_account_username || `账号 #${current}`,
        value: current,
      })
    }
    outlookOptions.value = options
  } catch (e) {
    message.error(`加载 Outlook 列表失败: ${e.message || e}`)
  } finally {
    outlookLoading.value = false
  }
}

function buildRowOutlookOptions(row) {
  const opts = outlookOptions.value.slice()
  // 如果当前行已绑定但不在可用池，补入当前绑定
  if (row.outlook_account_id && !opts.some((o) => o.value === row.outlook_account_id)) {
    opts.unshift({
      label: row.outlook_account_username || `账号 #${row.outlook_account_id}`,
      value: row.outlook_account_id,
    })
  }
  return opts
}

async function handleAssignOutlook(row, outlookAccountId) {
  try {
    await api.regAssignOutlook({
      registration_id: row.id,
      outlook_account_id: outlookAccountId ?? null,
    })
    message.success(outlookAccountId ? 'Outlook 已分配' : '已解绑 Outlook')
    $table.value?.handleSearch()
  } catch (e) {
    message.error(`操作失败: ${e.message || e}`)
  }
}

async function handleSaveTwoFaKey(row) {
  try {
    await api.regUpdateTwoFaKey({
      registration_id: row.id,
      two_fa_key: row.two_fa_key || '',
    })
    message.success('2FA Key 已保存')
    $table.value?.handleSearch()
  } catch (e) {
    message.error(`保存失败: ${e.message || e}`)
  }
}

async function handleBatchAssignOutlook() {
  batchAssignOutlookLoading.value = true
  try {
    const res = await api.regBatchAssignOutlook({ ids: checkedRowKeys.value })
    const d = res.data || {}
    message.success(`分配完成：成功 ${d.assigned || 0}，跳过 ${d.skipped || 0}，账号不足 ${d.no_account || 0}`)
    if (d.skip_reasons?.length) {
      message.info(d.skip_reasons.slice(0, 5).join('；'))
    }
    showBatchAssignOutlookModal.value = false
    checkedRowKeys.value = []
    $table.value?.handleSearch()
  } catch (e) {
    message.error(`批量分配失败: ${e.message || e}`)
  } finally {
    batchAssignOutlookLoading.value = false
  }
}

const statusOptions = [
  { label: '待处理', value: 'pending' },
  { label: '转发已创建', value: 'forwarding_created' },
  { label: '环境已创建', value: 'env_created' },
  { label: '注册中', value: 'registering' },
  { label: '已完成', value: 'completed' },
  { label: '失败', value: 'failed' },
]

const statusColorMap = {
  pending: 'default',
  forwarding_created: 'info',
  env_created: 'info',
  registering: 'warning',
  completed: 'success',
  failed: 'error',
}
const statusLabelMap = {
  pending: '待处理',
  forwarding_created: '转发已创建',
  env_created: '环境已创建',
  registering: '注册中',
  completed: '已完成',
  failed: '失败',
}

// ── 操作弹窗 ──
const showActionModal = ref(false)
const actionModalTitle = ref('')
const actionModalLoading = ref(false)
const actionType = ref('')
const actionTargetRow = ref(null)
const actionForm = reactive({ 
  country_id: 0, 
  application_id: 2, 
  max_price: null, 
  timeout: 300, 
  interval: 10,
  execute_now: false  // 同步执行开关
})
const actionFormRef = ref(null)

// ── 新增/编辑弹窗 ──
const modalVisible = ref(false)
const modalTitle = ref('新增注册')
const modalLoading = ref(false)
const modalFormRef = ref(null)

const modalForm = reactive({
  id: null,
  alias: '',
  domain: '',
  full_name: '',
  first_name: '',
  last_name: '',
  password: '',
  forward_to: '',
  zip_code: '',
  shipping_address_1: '',
  shipping_address_2: '',
  country: '',
  province_state: '',
  city: '',
  phone: '',
  registration_email: '',
  recovery_email: '',
  registration_status: 'pending',
  env_id: '',
  outlook_account_id: null,
  outlook_account_username: '',
})

function handleAdd() {
  modalTitle.value = '新增注册'
  Object.assign(modalForm, {
    id: null,
    alias: '',
    domain: '',
    full_name: '',
    first_name: '',
    last_name: '',
    password: '',
    forward_to: '',
    zip_code: '',
    shipping_address_1: '',
    shipping_address_2: '',
    country: '',
    province_state: '',
    city: '',
    phone: '',
    registration_email: '',
    recovery_email: '',
    registration_status: 'pending',
    env_id: '',
    outlook_account_id: null,
    outlook_account_username: '',
  })
  modalVisible.value = true
}

async function handleSave() {
  modalLoading.value = true
  try {
    if (!modalForm.alias || !modalForm.domain) {
      message.warning('别名和域名不能为空')
      modalLoading.value = false
      return
    }
    await api.regCreate({ ...modalForm })
    message.success('创建成功')
    modalVisible.value = false
    $table.value?.handleSearch()
  } catch (e) {
    message.error(e?.response?.data?.msg || '操作失败')
  } finally {
    modalLoading.value = false
  }
}

// ── 流程操作 ──

function openActionModal(type, row, title) {
  actionType.value = type
  actionTargetRow.value = row
  actionModalTitle.value = title
  showActionModal.value = true
}

async function confirmAction() {
  actionModalLoading.value = true
  const row = actionTargetRow.value
  try {
    switch (actionType.value) {
      case 'getPhone':
        await api.regGetPhone({
          registration_id: row.id,
          country_id: actionForm.country_id || null,
          application_id: actionForm.application_id || null,
          max_price: actionForm.max_price || null,
        })
        message.success('号码获取成功')
        break
      case 'waitSms':
        await api.regWaitSms({ registration_id: row.id, timeout: actionForm.timeout, interval: actionForm.interval })
        message.success('验证码接收成功')
        break
      case 'confirmSms':
        await api.regConfirmSms({ registration_id: row.id, status: 'used' })
        message.success('SMS 已确认')
        break
    }
    showActionModal.value = false
    $table.value?.handleSearch()
  } catch (e) {
    const errorMsg = e?.response?.data?.msg || e?.message || '操作失败'
    message.error(errorMsg)
  } finally {
    actionModalLoading.value = false
  }
}

// ── 批量操作 ──

function onCheckedChange(keys) {
  checkedRowKeys.value = keys
}

async function handleDeleteSingle(id) {
  try {
    await api.regBatchDelete([id])
    message.success('删除成功')
    $table.value?.handleSearch()
  } catch (e) {
    message.error(e?.response?.data?.msg || '删除失败')
  }
}

// ── 统一批量操作 ──

const batchOpMap = {
  getPhone: { api: 'regBatchGetPhone', label: '获取号码' },
  waitSms: { api: 'regBatchWaitSms', label: '等待短信' },
  confirmSms: { api: 'regBatchConfirmSms', label: '确认完成' },
}

async function handleBatchOp(op) {
  if (!checkedRowKeys.value.length) return
  const { api: apiMethod, label } = batchOpMap[op]
  batchLoading.value = op
  try {
    const res = await api[apiMethod](checkedRowKeys.value)
    const data = res.data || {}
    const successMsg = `${label}：成功 ${data.ok || 0} 条，失败 ${data.fail || 0} 条`
    message.success(successMsg)
    
    // 显示部分错误详情（最多 3 条）
    if (data.errors && data.errors.length > 0) {
      data.errors.slice(0, 3).forEach((err) => message.warning(err, { duration: 5000 }))
    }
    
    checkedRowKeys.value = []
    $table.value?.handleSearch()
  } catch (e) {
    const errorMsg = e?.response?.data?.msg || e?.message || `${label}失败`
    message.error(errorMsg)
    throw e
  } finally {
    batchLoading.value = null
  }
}

async function handleBatchDelete() {
  if (!checkedRowKeys.value.length) return
  batchDeleteLoading.value = true
  try {
    await api.regBatchDelete(checkedRowKeys.value)
    message.success(`已删除 ${checkedRowKeys.value.length} 条`)
    checkedRowKeys.value = []
    showBatchDeleteConfirm.value = false
    $table.value?.handleSearch()
  } catch (e) {
    message.error(e?.response?.data?.msg || '删除失败')
    throw e
  } finally {
    batchDeleteLoading.value = false
  }
}

async function handleBatchStatusUpdate() {
  if (!checkedRowKeys.value.length) return
  try {
    await api.regBatchUpdateStatus({
      ids: checkedRowKeys.value,
      registration_status: batchTargetStatus.value,
    })
    message.success('状态已更新')
    checkedRowKeys.value = []
    showBatchStatusModal.value = false
    $table.value?.handleSearch()
  } catch (e) {
    message.error(e?.response?.data?.msg || '更新失败')
  }
}

async function handleBatchFetch() {
  batchFetchLoading.value = true
  try {
    const res = await api.regBatchFetch({ alias: '' })
    const data = res.data || {}
    const parts = [`新增 ${data.created || 0} 条`]
    if (data.revived) parts.push(`恢复 ${data.revived} 条`)
    parts.push(`跳过 ${data.skipped || 0} 条`, `失败 ${data.failed || 0} 条`)
    message.success(parts.join('，'))
    if (data.skip_reasons?.length) {
      data.skip_reasons.slice(0, 3).forEach((r) => message.info(r))
    }
    $table.value?.handleSearch()
  } catch (e) {
    message.error(e?.response?.data?.msg || '批量获取失败')
  } finally {
    batchFetchLoading.value = false
  }
}

// ── 表格列定义 ──

const columns = [
  { type: 'selection', width: 40, align: 'center' },
  {
    title: '序号', key: '_index', width: 60, align: 'center',
    render: (_row, rowIndex) => (pagination.page - 1) * pagination.pageSize + rowIndex + 1,
  },
  {
    title: '站点域名', key: 'domain', width: 220,
    render: (row) => {
      const email = row.alias && row.domain ? `${row.alias}@${row.domain}` : (row.registration_email || '-')
      return h(NTooltip, { trigger: 'hover', placement: 'top' }, {
        trigger: () => h('div', { style: 'line-height:1.5;cursor:default' }, [
          h('div', { style: 'font-size:13px' }, `邮箱：${email}`),
          h('div', { style: 'font-size:12px;color:#909399' }, `域名：${row.domain || '-'}`),
        ]),
        default: () => h('div', { style: 'line-height:1.6' }, [
          h('div', null, `邮箱：${email}`),
          h('div', null, `域名：${row.domain || '-'}`),
        ]),
      })
    },
  },
  {
    title: '账号', key: 'outlook_account_username', width: 120, align: 'center',
    render: (row) => row.outlook_account_username ? h(
      NButton,
      {
        size: 'tiny',
        quaternary: true,
        onClick: () => {
          navigator.clipboard.writeText(row.outlook_account_username)
          message.success('账号已复制')
        },
      },
      { default: () => row.outlook_account_username },
    ) : '-',
  },
  {
    title: '密码', key: 'password', width: 120, align: 'center',
    render: (row) => row.password ? h(
      NButton,
      {
        size: 'tiny',
        quaternary: true,
        onClick: () => {
          navigator.clipboard.writeText(row.password)
          message.success('密码已复制')
        },
      },
      { default: () => row.password },
    ) : '-',
  },
  {
    title: '辅助邮箱', key: 'recovery_email', width: 120, align: 'center',
    render: (row) => row.recovery_email ? h(
      NButton,
      {
        size: 'tiny',
        quaternary: true,
        onClick: () => {
          navigator.clipboard.writeText(row.recovery_email)
          message.success('辅助邮箱已复制')
        },
      },
      { default: () => row.recovery_email },
    ) : '-',
  },
  {
    title: '2FA Key', key: 'two_fa_key', width: 80, align: 'center',
    render: (row) => {
      const hasTwoFa = !!row.two_fa_key
      return h(
        NTooltip,
        {},
        {
          trigger: () => h(
            'div',
            {
              style: { cursor: 'pointer', display: 'inline-flex', alignItems: 'center' },
              onClick: () => {
                if (hasTwoFa) {
                  navigator.clipboard.writeText(row.two_fa_key)
                  message.success('2FA Key 已复制')
                } else {
                  const inputValue = ref(row.two_fa_key || '')
                  dialog.create({
                    title: '回填 2FA Key',
                    content: () => h(NInput, {
                      value: inputValue.value,
                      placeholder: '请输入 Google 2FA Key',
                      clearable: true,
                      onUpdateValue: (val) => { inputValue.value = val },
                    }),
                    positiveText: '保存',
                    negativeText: '取消',
                    onPositiveClick: () => {
                      row.two_fa_key = inputValue.value
                      handleSaveTwoFaKey(row)
                    },
                  })
                }
              },
            },
            [
              h(TheIcon, {
                icon: hasTwoFa ? 'mdi:shield-check' : 'mdi:shield-off-outline',
                size: 20,
                color: hasTwoFa ? '#18a058' : '#d0d0d0',
              }),
            ],
          ),
          default: () => hasTwoFa ? '点击复制 2FA Key' : '点击回填 2FA Key',
        },
      )
    },
  },
  { title: '环境 ID', key: 'env_id', width: 130, align: 'center' },
  {
    title: 'SMS号码', key: 'sms_phone_number', width: 100, align: 'center',
    render: (row) => row.sms_phone_number ? h(
      NButton,
      {
        size: 'tiny',
        quaternary: true,
        onClick: () => {
          navigator.clipboard.writeText(row.sms_phone_number)
          message.success('号码已复制')
        },
      },
      { default: () => row.sms_phone_number },
    ) : null,
  },
  {
    title: '验证码', key: 'sms_code', width: 80, align: 'center',
    render: (row) => row.sms_code ? h(
      NButton,
      {
        size: 'tiny',
        quaternary: true,
        onClick: () => {
          navigator.clipboard.writeText(row.sms_code)
          message.success('验证码已复制')
        },
      },
      { default: () => row.sms_code },
    ) : null,
  },
  {
    title: '注册状态', key: 'registration_status', width: 90, align: 'center',
    render: (row) => h(
      NTag,
      { type: statusColorMap[row.registration_status] || 'default', size: 'small' },
      { default: () => statusLabelMap[row.registration_status] || row.registration_status },
    ),
  },
  {
    title: '操作', key: 'actions', width: 320, fixed: 'right',
    render: (row) => {
      const isCompleted = row.registration_status === 'completed'
      const hasPhone = row.sms_status === 'acquired'
      const hasCode = row.sms_status === 'code_received'

      return h(NSpace, { size: 'small', justify: 'start' }, {
        default: () => [
          h(NButton, { size: 'tiny', onClick: () => handleDetail(row) }, { default: () => '详情' }),
          h(NButton, {
            size: 'tiny',
            type: hasPhone ? 'default' : 'warning',
            disabled: isCompleted || hasPhone,
            onClick: () => openActionModal('getPhone', row, '获取号码'),
          }, { default: () => hasPhone ? '已取号' : '取号码' }),
          h(NButton, {
            size: 'tiny',
            type: hasCode ? 'default' : 'warning',
            disabled: isCompleted || hasCode || !hasPhone,
            onClick: () => openActionModal('waitSms', row, '等待验证码'),
          }, { default: () => hasCode ? '已验证' : '等验证码' }),
          h(NButton, {
            size: 'tiny',
            type: 'success',
            disabled: isCompleted || !hasCode,
            onClick: () => openActionModal('confirmSms', row, '确认完成'),
          }, { default: () => '完成' }),
          h(NPopconfirm, { onPositiveClick: () => handleDeleteSingle(row.id) }, {
            default: () => '确定删除？',
            trigger: () => h(NButton, { size: 'tiny', type: 'error' }, { default: () => '删除' }),
          }),
        ],
      })
    },
  },
]
</script>
