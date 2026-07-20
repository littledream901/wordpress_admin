<template>
  <CommonPage show-header title="站点流水线">
    <template #action>
      <n-space>
        <n-button v-permission="'post/api/v1/site-pipeline/site/create'" type="primary" @click="showAdd = true">新增站点</n-button>
        <n-button v-permission="'post/api/v1/site-pipeline/site/batch-create'" @click="showBatchAdd = true">批量新增</n-button>
      </n-space>
    </template>
    <n-space vertical :size="12">
      <CrudTable
        ref="$table"
        v-model:query-items="queryItems"
        :columns="columns"
        :get-data="api.getSiteList"
      >
        <template #queryBar>
          <n-input v-model:value="queryItems.domain" placeholder="域名搜索" clearable style="width: 200px" @keyup.enter="$table?.handleSearch()" />
          <n-tree-select
            v-model:value="queryItems.dept_id"
            :options="deptOption"
            key-field="id"
            label-field="name"
            placeholder="部门筛选"
            clearable
            style="width: 160px"
            default-expand-all
          />
          <n-select
            v-model:value="queryItems.assign_to"
            :options="userOption"
            label-field="label"
            value-field="value"
            placeholder="归属人筛选"
            clearable
            filterable
            style="width: 160px"
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
                <n-button v-for="item in batchActions" :key="item.key" v-permission="item.permission" @click="handleBatchActionClick(item.key)" style="justify-content: flex-start">
                  <template #icon>
                    <TheIcon :icon="item.icon" :size="18" />
                  </template>
                  {{ item.label }}
                </n-button>
              </n-button-group>
            </n-popover>
          </template>
        </template>
      </CrudTable>

      <!-- 批量操作确认弹窗 -->
      <n-modal v-model:show="showBatchConfirm" preset="dialog" title="确认批量操作"
        positive-text="确认"
        :loading="batchConfirmLoading"
        @positive-click="executeBatchAction"
        @negative-click="cancelBatchAction"
      >
        <div style="margin-bottom: 12px">
          确定要对 <b>{{ checkedRowKeys.length }}</b> 个站点执行
          <b>{{ currentBatchLabel }}</b> 操作吗？
        </div>
        <n-form-item v-if="currentBatchAction === 'redirect'" label="目标URL" label-placement="left">
          <n-input v-model:value="batchExtraTargetUrl" placeholder="https://target.com/$1" />
        </n-form-item>
        <template v-if="currentBatchAction === 'assign'">
          <n-form-item label="分配至部门" label-placement="left">
            <n-tree-select v-model:value="batchAssignDeptId" :options="deptOption" key-field="id" label-field="name" placeholder="留空不改变部门" clearable default-expand-all />
          </n-form-item>
          <n-form-item label="分配至用户" label-placement="left">
            <n-select v-model:value="batchAssignTo" :options="batchAssignUserOption" label-field="label" value-field="value" placeholder="留空不改变归属人" clearable filterable />
          </n-form-item>
        </template>
      </n-modal>

      <!-- 批量新增站点弹窗 -->
      <n-modal v-model:show="showBatchAdd" preset="card" title="批量新增站点" style="max-width: 600px">
        <n-space vertical :size="8">
          <n-form-item label="平台" label-placement="left" label-width="60">
            <n-select v-model:value="batchAddPlatform" :options="platformOptions" style="width:200px" />
          </n-form-item>
          <n-text depth="3">{{ batchAddHint }}</n-text>
          <n-input
            v-model:value="batchAddText"
            type="textarea"
            :rows="12"
            :placeholder="batchAddPlaceholder"
          />
        </n-space>
        <template #footer>
          <n-space justify="end">
            <n-button @click="showBatchAdd = false">取消</n-button>
            <n-button v-permission="'post/api/v1/site-pipeline/site/batch-create'" type="primary" @click="doBatchAdd" :loading="batchAddLoading">批量新增</n-button>
          </n-space>
        </template>
      </n-modal>

      <!-- 批量新增结果弹窗 -->
      <n-modal v-model:show="showBatchAddResult" preset="card" title="批量新增站点" style="max-width: 550px">
        <n-space vertical :size="8">
          <n-space align="center">
            <n-tag type="info" size="small">已提交 {{ batchAddTotal }} 个站点</n-tag>
            <n-text depth="3" style="font-size:13px">批次 {{ batchAddBatchId }} | 任务 #{{ batchAddJobId }}</n-text>
          </n-space>
          <n-text depth="3" style="font-size:12px">
            后台正在处理中，可在 <n-a href="#/operation-jobs/job-list" style="cursor:pointer">任务中心</n-a> 查看详情
          </n-text>
        </n-space>
        <template #footer>
          <n-space justify="end">
            <n-button type="primary" size="small" @click="showBatchAddResult = false; router.push('/operation-jobs/job-list')">查看任务中心</n-button>
            <n-button @click="showBatchAddResult = false; reload()">关闭</n-button>
          </n-space>
        </template>
      </n-modal>

      <!-- 新增 / 编辑弹窗 -->
      <n-modal v-model:show="showAdd" preset="card" :title="editId ? '编辑站点' : '新增站点'" style="max-width: 480px">
        <n-form ref="formRef" :model="formData" :rules="formRules" label-placement="left" label-width="90">
          <n-form-item label="域名" path="domain">
            <n-input v-model:value="formData.domain" placeholder="example.com" />
          </n-form-item>
          <n-form-item label="平台" path="platform">
            <n-select v-model:value="formData.platform" :options="platformOptions" />
          </n-form-item>
          <n-form-item label="服务器IP" path="server_ip">
            <n-input v-model:value="formData.server_ip" placeholder="1.2.3.4" />
          </n-form-item>
          <n-form-item label="所属部门" path="dept_id">
            <n-tree-select
              v-model:value="formData.dept_id"
              :options="deptOption"
              key-field="id"
              label-field="name"
              placeholder="留空则使用当前用户部门"
              clearable
              default-expand-all
            />
          </n-form-item>
          <n-form-item label="分配给" path="assign_to">
            <n-select
              v-model:value="formData.assign_to"
              :options="userFormOption"
              label-field="label"
              value-field="value"
              placeholder="留空则归自己名下"
              clearable
              filterable
            />
          </n-form-item>
          <template v-if="formData.platform === 'shopify'">
            <n-form-item label="建站状态">
              <n-select v-model:value="formData.status" :options="statusOptions" />
            </n-form-item>
            <n-form-item label="API Key">
              <n-input v-model:value="formData.shopify_key" type="password" show-password-on="click" placeholder="beb9ecda5bff9d3a18d318cedb23b0f4" />
            </n-form-item>
            <n-form-item label="Store URL">
              <n-input v-model:value="formData.shopify_store_url" placeholder="https://xxx.myshopify.com" />
            </n-form-item>  
            <n-form-item label="API Token">
              <n-input v-model:value="formData.shopify_token" type="password" show-password-on="click" placeholder="shpat_xxx" />
            </n-form-item>
          </template>
        </n-form>
        <template #footer>
          <n-space justify="end">
            <n-button @click="showAdd = false">取消</n-button>
            <n-button v-permission="'post/api/v1/site-pipeline/site/update'" type="primary" @click="doSave" :loading="saving">保存</n-button>
          </n-space>
        </template>
      </n-modal>

      <!-- 单条重定向弹窗 -->
      <n-modal v-model:show="showSingleRedirect" preset="card" title="设置重定向" style="max-width: 480px">
        <n-form label-placement="left" label-width="90">
          <n-form-item label="目标URL">
            <n-input v-model:value="singleRedirectTargetUrl" placeholder="https://target.com/$1" />
          </n-form-item>
        </n-form>
        <template #footer>
          <n-space justify="end">
            <n-button @click="showSingleRedirect = false">取消</n-button>
            <n-button v-permission="'post/api/v1/site-pipeline/site/siteId/redirect'" type="primary" @click="doSingleRedirectConfirm" :loading="singleRedirectLoading">确认</n-button>
          </n-space>
        </template>
      </n-modal>

      <!-- 批量结果弹窗 -->
      <n-modal v-model:show="showBatchResult" preset="card" :title="`批量操作结果 — ${currentBatchLabel || ''}`" style="max-width: 700px">
        <n-space vertical :size="8" v-if="batchSummary">
          <n-space align="center">
            <n-tag :type="batchIsAsync ? 'info' : 'success'" size="small" :bordered="false">{{ batchIsAsync ? '已提交' : '成功' }} {{ batchSuccessCount }}</n-tag>
            <n-tag type="error" size="small" :bordered="false">失败 {{ batchFailCount }}</n-tag>
            <n-text depth="3" style="font-size:13px">总计 {{ batchTotalCount }} 项</n-text>
          </n-space>
          <n-text v-if="batchIsAsync" depth="3" style="font-size:12px">
            {{ batchSuccessCount }} 项已提交后台执行，可在 <n-a @click="goToJobs" style="cursor:pointer">任务中心</n-a> 查看进度
          </n-text>
        </n-space>
        <n-data-table
          :columns="batchResultColumns"
          :data="batchResults"
          :max-height="400"
          size="small"
        />
        <template #footer>
          <n-space justify="end">
            <n-button v-if="batchIsAsync" type="primary" size="small" @click="goToJobs">查看任务中心</n-button>
            <n-button @click="showBatchResult = false; reload()">关闭</n-button>
          </n-space>
        </template>
      </n-modal>

      <!-- Gmail 选择弹窗 -->
      <n-modal v-model:show="gmailVisible" preset="card" title="选择 Gmail 账号" style="width: 1000px">
        <n-space vertical>
          <n-space>
            <n-input v-model:value="gmailQuery.username" placeholder="搜索 Username" style="width: 240px" @keydown.enter.prevent="loadGmailList" />
            <n-button type="primary" @click="loadGmailList">搜索</n-button>
          </n-space>
          <n-data-table :columns="gmailColumns" :data="gmailRows" :pagination="false" :max-height="500" size="small" />
        </n-space>
      </n-modal>

      <!-- 站点详情弹窗 -->
      <n-modal v-model:show="showDetail" preset="card" title="站点详情" style="max-width: 960px" :loading="detailLoading">
        <n-space vertical size="large" v-if="detail">
          <n-card title="基础信息" size="small">
            <n-descriptions label-placement="left" :column="2" bordered size="small">
              <n-descriptions-item label="ID">{{ detail.site.id }}</n-descriptions-item>
              <n-descriptions-item label="域名">{{ detail.site.domain }}</n-descriptions-item>
              <n-descriptions-item label="服务器IP">{{ detail.site.server_ip }}</n-descriptions-item>
              <n-descriptions-item label="站点状态">{{ detail.site.status }}</n-descriptions-item>
              <n-descriptions-item label="所属部门">{{ detail.site.dept_name || '-' }}</n-descriptions-item>
              <n-descriptions-item label="数据归属人">{{ detail.site.assign_to_name || '-' }}</n-descriptions-item>
              <n-descriptions-item label="Cloudflare">{{ detail.site.cloudflare_status }}</n-descriptions-item>
              <n-descriptions-item label="Dynadot">{{ detail.site.dynadot_status }}</n-descriptions-item>
              <n-descriptions-item label="Hub状态">{{ detail.site.hub_status }}</n-descriptions-item>
              <n-descriptions-item label="Hub环境ID">{{ detail.site.hub_env_id }}</n-descriptions-item>
              <n-descriptions-item label="流水线状态">{{ detail.site.pipeline_status }}</n-descriptions-item>
            </n-descriptions>
          </n-card>
          <n-card v-if="detail.site.platform === 'wordpress'" title="站点与 Woo 信息" size="small">
            <n-descriptions label-placement="left" :column="1" bordered size="small">
              <n-descriptions-item label="登录地址">{{ detail.site.login_url }}</n-descriptions-item>
              <n-descriptions-item label="Woo CK">{{ detail.site.woo_ck }}</n-descriptions-item>
              <n-descriptions-item label="Woo CS">{{ detail.site.woo_cs }}</n-descriptions-item>
              <n-descriptions-item label="CTX Refresh URL">{{ detail.site.ctx_refresh_url }}</n-descriptions-item>
              <n-descriptions-item label="Feed Link">{{ detail.site.feed_link }}</n-descriptions-item>
            </n-descriptions>
          </n-card>
          <n-card v-if="detail.site.platform === 'shopify'" title="Shopify 配置" size="small">
            <template #header-extra>
              <n-button size="tiny" type="primary" @click="openShopifyEdit">编辑</n-button>
            </template>
            <n-descriptions label-placement="left" :column="1" bordered size="small">
              <n-descriptions-item label="建站状态">{{ detail.site.status || '-' }}</n-descriptions-item>
              <n-descriptions-item label="API Key">
                <template v-if="detail.site.shopify_key">
                  {{ detail.site.shopify_key.substring(0, 8) }}...
                </template>
                <template v-else>-</template>
              </n-descriptions-item>
              <n-descriptions-item label="Store URL">{{ detail.site.shopify_store_url || '-' }}</n-descriptions-item>
              <n-descriptions-item label="API Token">
                <template v-if="detail.site.shopify_token">
                  {{ detail.site.shopify_token.substring(0, 8) }}...
                </template>
                <template v-else>-</template>
              </n-descriptions-item>
            </n-descriptions>
          </n-card>
          <!-- Shopify 配置编辑弹窗 -->
          <n-modal v-model:show="showShopifyEdit" preset="card" title="编辑 Shopify 配置" style="max-width: 480px">
            <n-form label-placement="left" label-width="100">
              <n-form-item label="建站状态">
                <n-select v-model:value="shopifyForm.status" :options="statusOptions" />
              </n-form-item>
              <n-form-item label="API Key">
                <n-input v-model:value="shopifyForm.key" type="password" show-password-on="click" placeholder="beb9ecda5bff9d3a18d318cedb23b0f4" />
              </n-form-item>
              <n-form-item label="Store URL">
                <n-input v-model:value="shopifyForm.store_url" placeholder="https://xxx.myshopify.com" />
              </n-form-item>
              <n-form-item label="API Token">
                <n-input v-model:value="shopifyForm.token" type="password" show-password-on="click" placeholder="shpat_xxx" />
              </n-form-item>
            </n-form>
            <template #footer>
              <n-space justify="end">
                <n-button @click="showShopifyEdit = false">取消</n-button>
                <n-button v-permission="'post/api/v1/site-pipeline/site/update'" type="primary" @click="saveShopifyConfig" :loading="shopifySaving">保存</n-button>
              </n-space>
            </template>
          </n-modal>
          <n-card title="Gmail 分配信息" size="small">
            <n-descriptions v-if="detail.gmail" label-placement="left" :column="2" bordered size="small">
              <n-descriptions-item label="Username">{{ detail.gmail.username }}</n-descriptions-item>
              <n-descriptions-item label="Password">{{ detail.gmail.password }}</n-descriptions-item>
              <n-descriptions-item label="Recovery Email">{{ detail.gmail.recovery_email }}</n-descriptions-item>
              <n-descriptions-item label="Phone">{{ detail.gmail.phone || '-' }}</n-descriptions-item>
              <n-descriptions-item label="Full Address" :span="2">{{ gmailFullAddress }}</n-descriptions-item>
              <n-descriptions-item label="2FA Link" :span="2">
                <n-a v-if="detail.gmail.link_to_generate_login_code" :href="detail.gmail.link_to_generate_login_code" target="_blank" style="word-break:break-all">{{ detail.gmail.link_to_generate_login_code }}</n-a>
                <span v-else>-</span>
              </n-descriptions-item>
            </n-descriptions>
            <n-empty v-else description="未分配 Gmail" />
          </n-card>
          <n-card title="Provider 绑定" size="small" v-if="detail.providers">
            <n-descriptions label-placement="left" :column="2" bordered size="small">
              <n-descriptions-item v-for="(p, type) in detail.providers" :key="type" :label="providerTypeLabel(type)">
                <n-tag :type="p.bound ? 'success' : 'default'" size="small" :bordered="false">
                  {{ p.provider_name }}{{ !p.bound && p.is_default ? ' (默认)' : '' }}
                </n-tag>
                <span v-if="p.bound && p.is_default" style="margin-left:4px;opacity:0.5;font-size:11px">(默认)</span>
                <span v-if="!p.bound && !p.provider_id" style="opacity:0.5;font-size:11px">未配置</span>
              </n-descriptions-item>
            </n-descriptions>
          </n-card>
          <n-card title="流水线日志" size="small">
            <n-input type="textarea" :value="detail.site.pipeline_log || ''" :rows="12" readonly />
          </n-card>
        </n-space>
      </n-modal>
    </n-space>
  </CommonPage>
</template>

<script setup>
import { ref, reactive, h, onMounted, computed, watch, resolveDirective, withDirectives } from 'vue'
import { useRouter } from 'vue-router'
import { NTag, NSpace, NButton, NCheckbox, NSelect, NTreeSelect, useMessage, useNotification } from 'naive-ui'
import api from '@/api/site-pipeline'
import baseApi from '@/api'
import gmailApi from '@/api/gmail'
import { isForceLoggingOut, registerStopAllPollingHandler } from '@/utils'
import CommonPage from '@/components/page/CommonPage.vue'
import CrudTable from '@/components/table/CrudTable.vue'
import TheIcon from '@/components/icon/TheIcon.vue'

const vPermission = resolveDirective('permission')

const message = useMessage()
const router = useRouter()
const notification = useNotification()

// ─── CrudTable ───
const $table = ref(null)
const queryItems = reactive({ domain: '', dept_id: null, assign_to: null })
const reload = () => $table.value?.handleSearch()

// ─── 详情弹窗 ───
const showDetail = ref(false)
const detail = ref(null)
const detailLoading = ref(false)
const loadDetail = async (id) => {
  showDetail.value = true
  detailLoading.value = true
  try {
    const res = await api.getSiteById({ site_id: id })
    detail.value = (res && res.data) ? res.data : null
  } catch (e) {
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

// ─── Gmail 选择弹窗 ───
const gmailVisible = ref(false)
const gmailRows = ref([])
const gmailQuery = reactive({ username: '' })
const assignTargetSiteId = ref(null)

const gmailColumns = [
  { title: '序号', key: 'index', width: 50, align: 'center', render: (_, index) => index + 1 },
  { title: 'Username', key: 'username', width: 200, ellipsis: { tooltip: true } },
  { title: 'Password', key: 'password', width: 220, ellipsis: { tooltip: true } },
  { title: '状态', key: 'status', width: 70 },
  { title: '已分配站点', key: 'assigned_site_domain', width: 150, ellipsis: { tooltip: true } },
  {
    title: '操作', key: 'actions', width: 130,
    render: (row) => withDirectives(h(NButton, { size: 'small', type: 'primary', onClick: () => assignGmail(row.id) }, { default: () => '分配到此站点' }), [[vPermission, 'post/api/v1/gmail/assign']]),
  },
]

async function loadGmailList() {
  try {
    const r = await gmailApi.getList({ page: 1, page_size: 50, username: gmailQuery.username, unassigned_only: true })
    gmailRows.value = r?.data ?? []
  } catch (_) {
    gmailRows.value = []
  }
}

async function assignGmail(gmailId) {
  try {
    await gmailApi.assign({ gmail_id: gmailId, site_id: assignTargetSiteId.value })
    message.success('Gmail 分配成功')
    gmailVisible.value = false
    reload()
  } catch (e) {
    message.error(e?.response?.data?.msg || '分配失败')
  }
}

function providerTypeLabel(type) {
  const map = { cloudflare: 'Cloudflare', dynadot: 'Dynadot', onepanel: '1Panel', hubstudio: 'HubStudio' }
  return map[type] || type
}

const gmailFullAddress = computed(() => {
  const g = detail.value?.gmail
  if (!g) return '-'
  const parts = [
    g.shipping_address_1, g.shipping_address_2,
    g.city, g.province_state, g.zip_code, g.country,
  ].filter(Boolean)
  return parts.join(', ') || '-'
})

// ─── Shopify 配置编辑（详情弹窗内） ───
const showShopifyEdit = ref(false)
const shopifySaving = ref(false)
const shopifyForm = reactive({ key: '', store_url: '', token: '', status: '' })
const shopifyCurrentSiteId = ref(null)
const statusOptions = [
  { label: '待建站', value: '待建站' },
  { label: '已建站', value: '已建站' },
]
function openShopifyEdit() {
  shopifyCurrentSiteId.value = detail.value?.site?.id
  shopifyForm.key = detail.value?.site?.shopify_key || ''
  shopifyForm.store_url = detail.value?.site?.shopify_store_url || ''
  shopifyForm.token = detail.value?.site?.shopify_token || ''
  shopifyForm.status = detail.value?.site?.status || '待建站'
  showShopifyEdit.value = true
}
async function saveShopifyConfig() {
  shopifySaving.value = true
  try {
    await api.updateSite({
      id: shopifyCurrentSiteId.value,
      status: shopifyForm.status,
      shopify_key: shopifyForm.key,
      shopify_store_url: shopifyForm.store_url,
      shopify_token: shopifyForm.token,
    })
    message.success('保存成功')
    showShopifyEdit.value = false
    // 刷新详情弹窗数据
    if (shopifyCurrentSiteId.value) {
      const r = await api.getSiteById({ site_id: shopifyCurrentSiteId.value })
      if (r?.data) detail.value = r.data
    }
  } catch (e) {
    message.error(e?.response?.data?.msg || '保存失败')
  } finally {
    shopifySaving.value = false
  }
}

// ─── 搜索 & 表单 ───
const showAdd = ref(false)
const editId = ref(null)
const saving = ref(false)
const formRef = ref(null)
const formData = reactive({ domain: '', server_ip: '', platform: 'wordpress', dept_id: null, assign_to: null, status: '', shopify_key: '', shopify_store_url: '', shopify_token: '' })
const platformOptions = [
  { label: 'WordPress (1Panel 建站)', value: 'wordpress' },
  { label: 'Shopify (手动配置)', value: 'shopify' },
]
const formRules = {
  domain: { required: true, message: '域名必填', trigger: 'blur' },
}

// ─── 部门 & 用户选择 ───
const deptOption = ref([])
const rawUserList = ref([])
const userOption = computed(() => {
  if (!queryItems.dept_id) return rawUserList.value
  return rawUserList.value.filter((u) => u.dept?.id === queryItems.dept_id)
})

// 表单的用户选择器：与所选部门联动，排除 admin
const userFormOption = computed(() => {
  const list = formData.dept_id
    ? rawUserList.value.filter((u) => u.dept?.id === formData.dept_id)
    : rawUserList.value
  return list.filter((u) => u.username !== 'admin')
})

// 表单中选了用户后，自动同步其部门
watch(() => formData.assign_to, (uid) => {
  if (uid) {
    const user = rawUserList.value.find((u) => u.value === uid)
    if (user?.dept?.id) {
      formData.dept_id = user.dept.id
    }
  }
})

// 部门切换时，若已选的归属人不在该部门，自动清空
watch(() => queryItems.dept_id, (newDeptId) => {
  if (newDeptId && queryItems.assign_to) {
    const validIds = userOption.value.map((u) => u.value)
    if (!validIds.includes(queryItems.assign_to)) {
      queryItems.assign_to = null
    }
  }
})

// ─── 表格 ───
const checkedRowKeys = ref([])

const checkedAll = computed({
  get: () => {
    const rows = $table.value?.tableData || []
    return rows.length > 0 && checkedRowKeys.value.length === rows.length
  },
  set: (v) => {
    const rows = $table.value?.tableData || []
    if (v) checkedRowKeys.value = rows.map((r) => r.id)
    else checkedRowKeys.value = []
  },
})

const columns = [
  {
    title: () => h(NCheckbox, { checked: checkedAll.value, onUpdateChecked: (v) => { checkedAll.value = v } }),
    key: 'select',
    width: 44,
    render: (row) => h(NCheckbox, {
      checked: checkedRowKeys.value.includes(row.id),
      onUpdateChecked: (v) => {
        if (v) checkedRowKeys.value = [...checkedRowKeys.value, row.id]
        else checkedRowKeys.value = checkedRowKeys.value.filter((k) => k !== row.id)
      },
    }),
  },
  { title: '序号', key: 'index', width: 50, align: 'center', render: (_, index) => index + 1 },
  { title: '域名', key: 'domain', width: 140, ellipsis: { tooltip: true }, align: 'center' },
  { title: '服务器IP', key: 'server_ip', width: 140, align: 'center',
    render: (r) => r.platform === 'shopify' ? h('span', { style: 'color:#999' }, '-') : (r.server_ip || '-'),
  },
  { title: '平台', key: 'platform', width: 60, render: (r) => h(NTag, { type: r.platform === 'shopify' ? 'success' : 'info', size: 'small' }, { default: () => r.platform === 'shopify' ? 'Shopify' : 'WP' }), align: 'center' },
  { title: '解析状态', key: 'cloudflare_status', width: 70, render: (r) => statusTag(r.cloudflare_status), align: 'center' },
  { title: '站点状态', key: 'status', width: 70, render: (r) => statusTag(r.status), align: 'center' },
  { title: '产品数', key: 'woo_product_count', width: 70, align: 'center',
    render: (row) => {
      const count = row.woo_product_count || 0
      return h(NSpace, { size: 4, justify: 'center', align: 'center' }, {
        default: () => [
          h('span', { style: 'font-weight:600;min-width:24px' }, count),
          withDirectives(h(NButton, { size: 'tiny', quaternary: true, onClick: (e) => { e.stopPropagation(); syncProductCount(row.id, row) } },
            { default: () => h(TheIcon, { icon: 'mdi:sync', size: 14 }) }
          ), [[vPermission, 'post/api/v1/site-pipeline/site/{site_id}/refresh-woo-count']]),
        ],
      })
    },
  },
  { title: 'Gmail', key: 'gmail_username', width: 70, render: (r) => r.gmail_username ? h(NTag, { type: 'success', size: 'small' }, { default: () => '已分配' }) : h(NTag, { type: 'default', size: 'small' }, { default: () => '未分配' }), align: 'center' },
  { title: 'Hub 状态', key: 'hub_status', width: 120, render: (r) => statusTag(r.hub_status), align: 'center' },
  { title: 'GMC', key: 'gmc_status', width: 80, render: (r) => statusTag(r.gmc_status), align: 'center' },
  { title: '重定向', key: 'pipeline_status', width: 80, render: (r) => statusTag(redirectLabel(r)), align: 'center' },
  { title: '操作', key: 'actions', width: 400,
    render: (row) => {
      const dnsOk = (row.cloudflare_status || '').includes('success') || (row.cloudflare_status || '').includes('已解析')
      const redirectOk = (row.pipeline_status || '').startsWith('redirect:')
      const provisionOk = (row.status || '').includes('已创建') || (row.status || '').includes('已存在')
      const importOk = (row.woo_import_status || '').includes('成功')

      return h(NSpace, { size: 'small' }, {
        default: () => [
          h(NButton, { size: 'tiny', onClick: () => goDetail(row.id) }, { default: () => '详情' }),
          withDirectives(h(NButton, { size: 'tiny', onClick: () => openEdit(row) }, { default: () => '编辑' }), [[vPermission, 'post/api/v1/site-pipeline/site/update']]),
          withDirectives(h(NButton, { size: 'tiny', type: 'info', ghost: !dnsOk, onClick: () => doSingleAction('dns', row.id) }, { default: () => 'DNS+NS' }), [[vPermission, 'post/api/v1/site-pipeline/site/siteId/dns']]),
          row.platform === 'shopify'
            ? h(NButton, { size: 'tiny', type: 'default', disabled: true }, { default: () => '建站' })
            : withDirectives(h(NButton, { size: 'tiny', type: 'success', ghost: !provisionOk, onClick: () => doSingleAction('provision', row.id) }, { default: () => '建站' }), [[vPermission, 'post/api/v1/site-pipeline/site/siteId/provision']]),
          withDirectives(h(NButton, { size: 'tiny', type: 'primary', ghost: !importOk, onClick: () => doSingleAction('woo-import', row.id) }, { default: () => '导入产品' }), [[vPermission, 'post/api/v1/site-pipeline/site/siteId/woo-import']]),
          withDirectives(h(NButton, { size: 'tiny', type: 'warning', ghost: !redirectOk, onClick: () => doSingleAction('redirect', row.id) }, { default: () => '重定向' }), [[vPermission, 'post/api/v1/site-pipeline/site/siteId/redirect']]),
          row.gmail_username
            ? withDirectives(h(NButton, { size: 'tiny', type: 'success', onClick: () => doSingleAction('unassign-gmail', row.id) }, { default: () => '取消Gmail' }), [[vPermission, 'post/api/v1/gmail/unassign']])
            : withDirectives(h(NButton, { size: 'tiny', type: 'tertiary', ghost: true, onClick: () => doSingleAction('assign-gmail', row.id) }, { default: () => '分配Gmail' }), [[vPermission, 'post/api/v1/gmail/assign']]),
        ],
      })
    },
  },
]

const batchResultColumns = computed(() => {
  const cols = [
    { title: '站点ID', key: 'site_id', width: 60 },
    { title: '域名', key: 'domain', ellipsis: { tooltip: true }, width: 120 },
  ]
  if (batchIsAsync.value) {
    cols.push(
      { title: '任务ID', key: 'job_id', width: 50 },
      { title: '产品数', key: 'woo_product_count', width: 60, render: (r) => r.woo_product_count || '-' },
      { title: '状态', key: 'status', width: 90, render: (r) => h(NTag, { type: r.status === 'running' ? 'info' : r.ok ? 'success' : 'error', size: 'small' }, { default: () => r.status || (r.ok ? '已提交' : '失败') }) },
    )
  } else {
    cols.push(
      { title: '结果', key: 'ok', width: 60, render: (r) => h(NTag, { type: r.ok ? 'success' : 'error', size: 'small' }, { default: () => r.ok ? '成功' : '失败' }) },
    )
  }
  cols.push({ title: '详情', key: 'error', ellipsis: { tooltip: true }, render: (r) => r.error ? h('span', { style: 'color:#d03050' }, r.error) : (r.ok ? '-' : '失败') })
  return cols
})

// ─── 批量操作 ───
const showBatchMenu = ref(false)
const showBatchConfirm = ref(false)
const showBatchResult = ref(false)
const batchConfirmLoading = ref(false)
const currentBatchAction = ref('')
const currentBatchLabel = ref('')
const batchResults = ref([])
const batchSummary = ref('')
const batchExtraNsList = ref('')
const batchExtraTargetUrl = ref('')
const batchAssignDeptId = ref(null)
const batchAssignTo = ref(null)

// 批量分配弹窗：用户选项与所选部门联动，排除 admin
const batchAssignUserOption = computed(() => {
  const list = batchAssignDeptId.value
    ? rawUserList.value.filter((u) => u.dept?.id === batchAssignDeptId.value)
    : rawUserList.value
  return list.filter((u) => u.username !== 'admin')
})
watch(batchAssignDeptId, (newDeptId) => {
  if (newDeptId && batchAssignTo.value) {
    const validIds = batchAssignUserOption.value.map((u) => u.value)
    if (!validIds.includes(batchAssignTo.value)) {
      batchAssignTo.value = null
    }
  }
})

const batchSuccessCount = computed(() => batchResults.value.filter(r => r.ok).length)
const batchFailCount = computed(() => batchResults.value.filter(r => !r.ok).length)
const batchTotalCount = computed(() => batchResults.value.length)
// 异步操作（返回 job_id 后台运行）
const batchIsAsync = computed(() => ['dns', 'provision', 'woo-import', 'redirect'].includes(batchResultActionType.value))

function goToJobs() {
  showBatchResult.value = false
  router.push('/operation-jobs/job-list')
}

const batchResultActionType = ref('')

// ─── 单条重定向 ───
const showSingleRedirect = ref(false)
const singleRedirectSiteId = ref(null)
const singleRedirectTargetUrl = ref('')
const singleRedirectLoading = ref(false)

// ─── 批量新增 ───
const showBatchAdd = ref(false)
const batchAddText = ref('')
const batchAddLoading = ref(false)
const batchAddPlatform = ref('wordpress')
const showBatchAddResult = ref(false)
const batchAddTotal = ref(0)
const batchAddBatchId = ref('')
const batchAddJobId = ref(0)

const batchAddHint = computed(() => batchAddPlatform.value === 'shopify'
  ? '每行一个域名（Shopify 配置后续到编辑页面补充）'
  : '每行一个站点，格式：域名,服务器IP（用逗号或 Tab 分隔，IP 可省略）')

const batchAddPlaceholder = computed(() => batchAddPlatform.value === 'shopify'
  ? 'my-store.com\nanother-store.com'
  : 'example.com,1.2.3.4\nmyshop.com,5.6.7.8\nblog.org')

const batchActionLabelMap = {
  dns: '批量 DNS+NS',
  provision: '批量建站',
  'woo-import': '批量导入产品',
  redirect: '批量重定向',
  'assign-gmail': '批量分配Gmail',
  assign: '批量分配用户',
  delete: '批量删除',
}

const batchActions = [
  { label: '批量 DNS+NS', key: 'dns', icon: 'mdi:cloud-check', permission: 'post/api/v1/site-pipeline/site/batch-dns' },
  { label: '批量建站', key: 'provision', icon: 'mdi:rocket-launch', permission: 'post/api/v1/site-pipeline/site/batch-provision' },
  { label: '批量导入产品', key: 'woo-import', icon: 'mdi:import', permission: 'post/api/v1/site-pipeline/site/batch-woo-import' },
  { label: '批量重定向', key: 'redirect', icon: 'mdi:arrow-decision', permission: 'post/api/v1/site-pipeline/site/batch-redirect' },
  { label: '批量分配Gmail', key: 'assign-gmail', icon: 'mdi:email-arrow-right', permission: 'post/api/v1/gmail/batch-auto-assign' },
  { label: '批量分配用户', key: 'assign', icon: 'mdi:account-arrow-right', permission: 'post/api/v1/site-pipeline/site/batch-assign' },
  { label: '批量删除', key: 'delete', icon: 'mdi:delete', permission: 'post/api/v1/site-pipeline/site/batch-delete' },
]

function handleBatchActionClick(key) {
  showBatchMenu.value = false
  handleBatchActionSelect(key)
}

function handleBatchActionSelect(key) {
  if (!checkedRowKeys.value.length) return
  currentBatchAction.value = key
  currentBatchLabel.value = batchActionLabelMap[key] || key
  batchExtraNsList.value = ''
  batchExtraTargetUrl.value = ''
  batchAssignDeptId.value = null
  batchAssignTo.value = null
  showBatchConfirm.value = true
}

function cancelBatchAction() {
  currentBatchAction.value = ''
  batchExtraNsList.value = ''
  batchExtraTargetUrl.value = ''
  batchAssignDeptId.value = null
  batchAssignTo.value = null
  showBatchConfirm.value = false
}

async function executeBatchAction() {
  if (!checkedRowKeys.value.length) return
  batchConfirmLoading.value = true
  const ids = [...checkedRowKeys.value]
  const action = currentBatchAction.value
  try {
    let res
    if (action === 'dns') {
      res = await api.batchDns(ids)
    } else if (action === 'provision') {
      res = await api.batchProvision(ids)
      const provResults = res?.data?.results ?? []
      const okCount = provResults.filter(r => r.ok).length
      const failCount = provResults.length - okCount
      if (okCount > 0) {
        notification.create({
          type: 'info',
          title: '批量建站已提交',
          content: () => {
            return h('div', { style: 'line-height: 1.8' }, [
              `已提交 ${okCount} 个建站任务`,
              failCount > 0 ? `，${failCount} 个失败` : '',
              h('br'),
              h('a', { href: 'javascript:void(0)', onClick: goToJobs, style: 'color: var(--primary-color); text-decoration: underline; cursor: pointer' }, '点击前往任务中心查看'),
            ])
          },
          duration: 15000,
          closable: true,
        })
      }
    } else if (action === 'woo-import') {
      res = await api.batchImportProducts(ids)
    } else if (action === 'redirect') {
      res = await api.batchRedirect(ids, batchExtraTargetUrl.value)
    } else if (action === 'assign-gmail') {
      res = await gmailApi.batchAutoAssign(ids)
    } else if (action === 'assign') {
      res = await api.batchAssign({
        site_ids: ids,
        dept_id: batchAssignDeptId.value,
        assign_to: batchAssignTo.value,
      })
    } else if (action === 'delete') {
      res = await api.batchDeleteSites(ids)
    }

    if (action === 'delete') {
      message.success(`已删除 ${res?.data?.deleted ?? 0} 条`)
    } else if (action === 'assign') {
      message.success(`已分配 ${res?.data?.updated ?? 0} / ${res?.data?.total ?? 0} 个站点`)
      showBatchConfirm.value = false
      reload()
    } else {
      batchResultActionType.value = action
      batchResults.value = res?.data?.results ?? []
      batchSummary.value = '1'  // truthy flag
      showBatchResult.value = true
    }

    checkedRowKeys.value = []
    currentBatchAction.value = ''
    reload()
  } catch (e) {
    message.error(e?.response?.data?.msg || '批量操作失败')
    throw e
  } finally {
    batchConfirmLoading.value = false
  }
}

// ─── 渲染工具 ───
function statusTag(val) {
  const s = val || ''
  let type = 'default'
  if (s.includes('success') || s.includes('updated') || s.includes('成功') || s.includes('已完成') || s.includes('已创建') || s.includes('已解析')) type = 'success'
  else if (s.includes('fail') || s.includes('error') || s.includes('失败')) type = 'error'
  else if (s.includes('ing') || s.includes('running')) type = 'info'
  return h(NTag, { type, size: 'small' }, { default: () => s || '-' })
}

function redirectLabel(row) {
  const s = row.pipeline_status || ''
  if (s.startsWith('redirect:')) return s.replace('redirect:', '')
  return ''
}

function goDetail(id) { loadDetail(id) }

function openEdit(row) {
  editId.value = row.id
  formData.domain = row.domain
  formData.server_ip = row.server_ip
  formData.platform = row.platform || 'wordpress'
  formData.dept_id = row.dept_id ?? null
  formData.assign_to = null
  formData.status = row.status ?? ''
  formData.shopify_key = row.shopify_key ?? ''
  formData.shopify_store_url = row.shopify_store_url ?? ''
  formData.shopify_token = row.shopify_token ?? ''
  showAdd.value = true
}

// ─── 新增 / 编辑 ───
async function doSave() {
  saving.value = true
  try {
    if (editId.value) {
      await api.updateSite({ id: editId.value, ...formData })
      message.success('更新成功')
    } else {
      await api.createSite(formData)
      message.success('创建成功')
    }
    showAdd.value = false
    editId.value = null
    formData.domain = ''
    formData.server_ip = ''
    formData.platform = 'wordpress'
    formData.dept_id = null
    formData.assign_to = null
    reload()
  } catch (e) {
    message.error(e?.message || e?.response?.data?.msg || '操作失败')
  } finally {
    saving.value = false
  }
}

// ─── 批量新增 ───
async function doBatchAdd() {
  const text = batchAddText.value.trim()
  if (!text) {
    message.warning('请输入站点信息')
    return
  }
  const platform = batchAddPlatform.value
  const lines = text.split('\n').filter(l => l.trim())
  const items = []
  for (const line of lines) {
    const parts = line.split(/[,\t]/).map(s => s.trim()).filter(Boolean)
    if (parts.length === 0) continue
    if (platform === 'shopify') {
      items.push({ domain: parts[0], server_ip: '', platform: 'shopify' })
    } else {
      items.push({ domain: parts[0], server_ip: parts[1] || '', platform: 'wordpress' })
    }
  }
  if (items.length === 0) {
    message.warning('未解析到有效站点')
    return
  }
  batchAddLoading.value = true
  try {
    const res = await api.batchCreateSites({ items })
    const d = res?.data ?? {}
    batchAddTotal.value = d.total ?? 0
    batchAddBatchId.value = d.batch_id ?? ''
    batchAddJobId.value = d.job_id ?? 0
    showBatchAddResult.value = true
    showBatchAdd.value = false
    batchAddText.value = ''
    message.success(`已提交 ${batchAddTotal.value} 个站点到后台处理`)
  } catch (e) {
    message.error(e?.response?.data?.msg || '批量新增失败')
  } finally {
    batchAddLoading.value = false
  }
}

// ─── 建站进度轮询（全局共享一个定时器） ───
const STEP_LABELS = {
  create_site: '创建站点',
  apply_ssl: '申请SSL',
  restore_db: '恢复数据库',
  restore_files: '恢复文件',
  rebuild_after_files: '重建容器(文件)',
  replace_domain: '域名替换',
  patch_wp_config: '修改WP配置',
  rebuild_after_patch: '重建容器(配置)',
  health_check: '健康检查',
  create_woo_ctx: '创建Woo+CTX',
  done: '完成',
}

const MAX_POLL_JOBS = 3                  // 当前页最多同时轮询的 job 数
const provisionJobs = new Map()          // key → { jobId, domain, n, pending: bool }
let provisionPoller = null               // 全局 setInterval id
let provisionPollRound = 0               // 轮询轮次（用于降低 pending 复查频率）

function startProvisionPolling(jobId, domain, siteId) {
  const key = `${siteId}_${jobId}`

  // 并发上限：超过上限不挂轮询，直接引导任务中心
  if (provisionJobs.size >= MAX_POLL_JOBS) {
    notification.create({
      type: 'info',
      title: '建站任务已提交',
      content: `任务 #${jobId} (${domain}) 已提交，当前轮询任务已达上限，请前往任务中心查看`,
      duration: 8000,
      closable: true,
    })
    return
  }

  // 清理旧的同 key 记录
  const old = provisionJobs.get(key)
  if (old) { old.n.destroy(); provisionJobs.delete(key) }

  const n = notification.create({
    title: `建站中: ${domain}`,
    content: '准备中...',
    duration: 0,
    closable: true,
    onClose: () => {
      provisionJobs.delete(key)
      if (provisionJobs.size === 0 && provisionPoller) {
        clearInterval(provisionPoller)
        provisionPoller = null
      }
    },
  })

  provisionJobs.set(key, {
    jobId,
    domain,
    n,
    pending: false,
    retries: 0,
    pollCount: 0,
    maxPollCount: 12,   // 12 × 5s = 60s 短轮询上限
  })

  // 确保全局轮询已启动
  if (!provisionPoller) {
    registerStopAllPollingHandler(_stopProvisionPoll)
    provisionPoller = setInterval(_pollAllProvision, 5000)
    _pollAllProvision()
  }
}

async function _pollAllProvision() {
  // 全局退出闸门：停止所有轮询
  if (isForceLoggingOut()) {
    _stopProvisionPoll()
    provisionJobs.clear()
    return
  }

  provisionPollRound++
  // 每 3 轮（15秒）复查一次 pending 任务是否已启动
  const recheckPending = provisionPollRound % 3 === 0

  const entries = [...provisionJobs.entries()]
  for (const [k, v] of entries) {
    // ── 轮询上限检查：12 次 × 5s = 60s，超时引导任务中心 ──
    v.pollCount = (v.pollCount || 0) + 1
    if (v.pollCount > (v.maxPollCount || 12)) {
      v.n.type = 'info'
      v.n.title = `后台继续执行: ${v.domain}`
      v.n.content = () => {
        return h('span', [
          `任务 #${v.jobId} 仍在执行，`,
          h('a', {
            href: 'javascript:void(0)',
            onClick: goToJobs,
            style: 'color: var(--primary-color); text-decoration: underline; cursor: pointer',
          }, '点击前往任务中心查看'),
        ])
      }
      v.n.duration = 12000
      v.n.closable = true
      provisionJobs.delete(k)
      continue
    }

    // 已知 pending 的跳过 API 调用，除非轮到复查
    if (v.pending && !recheckPending) continue
    if (!v.jobId) continue

    try {
      const res = await api.getJob({ id: v.jobId })
      const job = res?.data
      if (!job) continue

      if (job.status === 'pending') {
        v.pending = true
        v.n.content = '[等待中...]'
        continue
      }

      v.pending = false
      const label = STEP_LABELS[job.step] || job.step
      if (job.status === 'success') {
        v.n.type = 'success'
        v.n.title = `建站完成: ${v.domain}`
        v.n.content = `登录地址: https://${v.domain}/wp-admin`
        v.n.duration = 8000
        v.n.closable = true
        provisionJobs.delete(k)
        setTimeout(reload, 1000)
      } else if (job.status === 'failed' || job.status === 'cancelled') {
        v.n.type = job.status === 'cancelled' ? 'warning' : 'error'
        v.n.title = `建站${job.status === 'cancelled' ? '取消' : '失败'}: ${v.domain}`
        const cancelReason = (() => { try { return JSON.parse(job.result_json || '{}').cancel_reason } catch { return '' } })()
        v.n.content = job.error_message || cancelReason || (job.status === 'cancelled' ? '任务已被取消' : '未知错误')
        v.n.duration = 15000
        v.n.closable = true
        provisionJobs.delete(k)
        setTimeout(reload, 1000)
      } else {
        v.n.content = `[步骤] ${label}`
      }
    } catch (err) {
      // 全局退出触发的请求拒绝，静默停止轮询
      if (err?.__forceLogout) {
        provisionJobs.delete(k)
        _stopProvisionPoll()
        break
      }
      const code = err?.code || err?.response?.status || 0
      if (code === 404) {
        // 任务不存在（可能被清理），停止轮询
        v.n.type = 'warning'
        v.n.title = `任务丢失: ${v.domain}`
        v.n.content = `任务 #${v.jobId} 不存在`
        v.n.duration = 10000
        v.n.closable = true
        provisionJobs.delete(k)
      } else if (code === 401) {
        // 未登录或 token 过期，停止所有轮询
        v.n.content = '[登录已过期]'
        v.n.duration = 5000
        v.n.closable = true
        provisionJobs.delete(k)
        _stopProvisionPoll()
      } else if (code === 403 || code === 422) {
        // 无权限或数据异常，停止该任务轮询
        v.n.type = 'error'
        v.n.title = `轮询失败: ${v.domain}`
        v.n.content = `状态码 ${code}，已停止轮询`
        v.n.duration = 10000
        v.n.closable = true
        provisionJobs.delete(k)
      } else {
        // 500 / 网络异常：有限重试，超次数后停止
        v.retries = (v.retries || 0) + 1
        if (v.retries > 5) {
          v.n.type = 'error'
          v.n.title = `轮询中断: ${v.domain}`
          v.n.content = `连续失败 ${v.retries} 次，已停止轮询`
          v.n.duration = 10000
          v.n.closable = true
          provisionJobs.delete(k)
        }
      }
    }
  }
  // 没有任务了，停止全局轮询
  if (provisionJobs.size === 0 && provisionPoller) {
    _stopProvisionPoll()
  }
}

function _stopProvisionPoll() {
  if (provisionPoller) {
    clearInterval(provisionPoller)
    provisionPoller = null
  }
}

// ─── 单条操作 ───
async function doSingleAction(action, siteId) {
  try {
    if (action === 'dns') {
      await api.provisionDns(siteId)
      message.success('DNS+NS 已触发')
    } else if (action === 'provision') {
      const res = await api.provisionSite(siteId)
      const jobId = res?.data?.job_id
      if (jobId) {
        const rows = $table.value?.tableData || []
        const row = rows.find(r => r.id === siteId)
        startProvisionPolling(jobId, row?.domain || `站点#${siteId}`, siteId)
      } else {
        message.success('建站已触发')
      }
    } else if (action === 'woo-import') {
      const res = await api.importProducts(siteId)
      const data = res?.data
      if (data?.job_id) {
        const count = data.total || '?'
        message.success(`产品导入已触发：${count} 个产品，任务 #${data.job_id}`)
      } else {
        message.success('产品导入已触发')
      }
    } else if (action === 'redirect') {
      singleRedirectSiteId.value = siteId
      showSingleRedirect.value = true
      return
    } else if (action === 'assign-gmail') {
      assignTargetSiteId.value = siteId
      gmailQuery.username = ''
      gmailVisible.value = true
      loadGmailList()
      return
    } else if (action === 'unassign-gmail') {
      await gmailApi.unassign(siteId)
      message.success('Gmail 已取消分配')
    }
    setTimeout(reload, 1500)
  } catch (e) {
    message.error(e?.response?.data?.msg || '操作失败')
  }
}

// ─── 单条重定向确认 ───
async function doSingleRedirectConfirm() {
  if (!singleRedirectTargetUrl.value.trim()) {
    message.warning('请输入目标 URL')
    return
  }
  singleRedirectLoading.value = true
  try {
    await api.provisionRedirect(singleRedirectSiteId.value, { target_url: singleRedirectTargetUrl.value })
    message.success('重定向已触发')
    showSingleRedirect.value = false
    setTimeout(reload, 1500)
  } catch (e) {
    message.error(e?.response?.data?.msg || '操作失败')
  } finally {
    singleRedirectLoading.value = false
  }
}

// ─── 同步产品数量 ───
async function syncProductCount(siteId, row) {
  try {
    message.loading('正在查询远端产品数量...')
    const res = await api.refreshProductCount(siteId)
    const count = res?.data?.product_count ?? 0
    row.woo_product_count = count
    message.success(`站点 ${row.domain} 远端产品总数: ${count}`)
  } catch (e) {
    message.error(e?.response?.data?.msg || '查询失败')
  }
}

onMounted(() => {
  $table.value?.handleSearch()
  baseApi.getDepts().then((res) => (deptOption.value = res.data))
  baseApi.getUserList({ page: 1, page_size: 200 }).then((res) => {
    rawUserList.value = (res.data || []).map((u) => ({ label: `${u.username} (${u.dept?.name || '-'})`, value: u.id, username: u.username, dept: u.dept }))
  })
})
</script>
