<template>
  <CommonPage title="站点详情">
    <n-space vertical size="large">
      <n-card title="操作区" v-if="detail?.site">
        <n-space vertical>
          <n-space>
            <n-button @click="doDns">执行 DNS+NS</n-button>
            <n-button type="warning" @click="doDynadotNs">执行 Dynadot NS</n-button>
            <n-button type="primary" @click="doProvision">执行建站</n-button>
            <n-button type="warning" @click="doRedirect">执行 301 重定向</n-button>
            <n-button type="info" @click="doHub">执行 Hub 环境</n-button>
            <n-button type="success" @click="doWoo">执行 Woo 导入</n-button>
          </n-space>
          <n-space>
            <n-input-number v-model:value="assignProductCount" :min="1" :max="200" placeholder="随机分配数量" />
            <n-button type="success" @click="doRandomAssignProducts">随机给站点分配产品</n-button>
          </n-space>
        </n-space>
      </n-card>

      <n-card title="基础信息" v-if="detail?.site">
        <n-descriptions label-placement="left" :column="2" bordered>
          <n-descriptions-item label="ID">{{ detail.site.id }}</n-descriptions-item>
          <n-descriptions-item label="域名">{{ detail.site.domain }}</n-descriptions-item>
          <n-descriptions-item label="服务器IP">{{ detail.site.server_ip }}</n-descriptions-item>
          <n-descriptions-item label="站点状态">{{ detail.site.status }}</n-descriptions-item>
          <n-descriptions-item label="Cloudflare">{{ detail.site.cloudflare_status }}</n-descriptions-item>
          <n-descriptions-item label="Dynadot">{{ detail.site.dynadot_status }}</n-descriptions-item>
          <n-descriptions-item label="Hub状态">{{ detail.site.hub_status }}</n-descriptions-item>
          <n-descriptions-item label="Hub环境ID">{{ detail.site.hub_env_id }}</n-descriptions-item>
          <n-descriptions-item label="流水线状态">{{ detail.site.pipeline_status }}</n-descriptions-item>
        </n-descriptions>
      </n-card>

      <n-card title="站点与 Woo 信息" v-if="detail?.site">
        <n-descriptions label-placement="left" :column="1" bordered>
          <n-descriptions-item label="登录地址">{{ detail.site.login_url }}</n-descriptions-item>
          <n-descriptions-item label="Woo CK">{{ detail.site.woo_ck }}</n-descriptions-item>
          <n-descriptions-item label="Woo CS">{{ detail.site.woo_cs }}</n-descriptions-item>
          <n-descriptions-item label="CTX Refresh URL">{{ detail.site.ctx_refresh_url }}</n-descriptions-item>
          <n-descriptions-item label="Feed Link">{{ detail.site.feed_link }}</n-descriptions-item>
        </n-descriptions>
      </n-card>

      <n-card title="Gmail 分配信息">
        <template #header-extra>
          <n-button size="small" @click="openAssignDialog">分配 Gmail</n-button>
        </template>
        <n-descriptions v-if="detail?.gmail" label-placement="left" :column="2" bordered style="margin-top: 12px">
          <n-descriptions-item label="Username">{{ detail.gmail.username }}</n-descriptions-item>
          <n-descriptions-item label="Password">{{ detail.gmail.password }}</n-descriptions-item>
          <n-descriptions-item label="Full Name">{{ detail.gmail.full_name }}</n-descriptions-item>
          <n-descriptions-item label="First Name">{{ detail.gmail.first_name }}</n-descriptions-item>
          <n-descriptions-item label="Last Name">{{ detail.gmail.last_name }}</n-descriptions-item>
          <n-descriptions-item label="Recovery Email">{{ detail.gmail.recovery_email }}</n-descriptions-item>
          <n-descriptions-item label="Phone">{{ detail.gmail.phone }}</n-descriptions-item>
          <n-descriptions-item label="Country">{{ detail.gmail.country }}</n-descriptions-item>
          <n-descriptions-item label="Province/State">{{ detail.gmail.province_state }}</n-descriptions-item>
          <n-descriptions-item label="City">{{ detail.gmail.city }}</n-descriptions-item>
          <n-descriptions-item label="Zip Code">{{ detail.gmail.zip_code }}</n-descriptions-item>
          <n-descriptions-item label="Shipping Address 1">{{ detail.gmail.shipping_address_1 }}</n-descriptions-item>
          <n-descriptions-item label="Shipping Address 2">{{ detail.gmail.shipping_address_2 }}</n-descriptions-item>
          <n-descriptions-item label="2FA Key">{{ detail.gmail.two_fa_key }}</n-descriptions-item>
          <n-descriptions-item label="2FA Login Code Link">{{ detail.gmail.link_to_generate_login_code }}</n-descriptions-item>
        </n-descriptions>
        <n-empty v-else description="当前站点未分配 Gmail" style="margin-top: 12px" />
      </n-card>

      <n-card title="流水线日志" v-if="detail?.site">
        <n-input type="textarea" :value="detail.site.pipeline_log || ''" :rows="18" readonly />
      </n-card>
    </n-space>

    <n-modal v-model:show="gmailVisible" preset="card" title="选择 Gmail 账号" style="width: 1000px">
      <n-space vertical>
        <n-input v-model:value="gmailQuery.username" placeholder="搜索 Username" @keydown.enter.prevent="loadGmailList" />
        <n-button type="primary" @click="loadGmailList">搜索</n-button>
        <n-data-table :columns="gmailColumns" :data="gmailRows" :pagination="false" :max-height="500" />
      </n-space>
    </n-modal>
  </CommonPage>
</template>
<script setup>
import { h, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { NButton, useMessage, useNotification } from 'naive-ui'
import api from '@/api/site-pipeline'
import gmailApi from '@/api/gmail'
import shopifyApi from '@/api/shopify'

const route = useRoute()
const message = useMessage()
const notification = useNotification()
const detail = ref(null)
const assignProductCount = ref(6)
const gmailVisible = ref(false)
const gmailRows = ref([])
const gmailQuery = reactive({ username: '', status: '' })

const load = async () => {
  const id = route.query.site_id || route.params.id
  if (!id) return
  detail.value = (await api.getSiteById({ site_id: id })).data || null
}
const currentId = () => detail.value?.site?.id
const doDns = async () => { await api.provisionDns(currentId()); message.success('DNS+NS 已触发'); await load() }
const doDynadotNs = async () => { await api.provisionDynadotNs(currentId()); message.success('Dynadot NS 已触发'); await load() }
const STEP_LABELS = {
  create_site: '创建站点',
  restore_db: '恢复数据库',
  restore_files: '恢复文件',
  rebuild_after_files: '重建容器(文件)',
  replace_domain: '域名替换',
  patch_wp_config: '修改WP配置',
  rebuild_before_scripts: '重建容器(脚本)',
  create_woo_key: '创建WooCommerce密钥',
  create_ctx: '创建CTX脚本',
  fetch_feed: '获取Feed链接',
  done: '完成',
}

let provisionTimer = null

const doProvision = async () => {
  const siteId = currentId()
  const domain = detail.value?.site?.domain || ''
  try {
    const res = await api.provisionSite(siteId)
    const jobId = res?.data?.job_id
    if (jobId) {
      if (provisionTimer) clearInterval(provisionTimer)
      const n = notification.create({
        title: `建站中: ${domain}`,
        content: '准备中...',
        duration: 0,
        closable: true,
        onClose: () => {
          if (provisionTimer) { clearInterval(provisionTimer); provisionTimer = null }
        },
      })
      const poll = async () => {
        try {
          const jRes = await api.getJob({ id: jobId })
          const job = jRes?.data
          if (!job) return
          const label = STEP_LABELS[job.step] || job.step
          if (job.status === 'success') {
            n.type = 'success'
            n.title = `建站完成: ${domain}`
            n.content = `登录地址: https://${domain}/wp-admin`
            n.duration = 8000
            n.closable = true
            clearInterval(provisionTimer)
            provisionTimer = null
            await load()
          } else if (job.status === 'failed') {
            n.type = 'error'
            n.title = `建站失败: ${domain}`
            n.content = job.error_message || '未知错误'
            n.duration = 15000
            n.closable = true
            clearInterval(provisionTimer)
            provisionTimer = null
            await load()
          } else {
            n.content = `[步骤] ${label}`
          }
        } catch (_) {}
      }
      poll()
      provisionTimer = setInterval(poll, 5000)
    } else {
      message.success('建站已触发')
      await load()
    }
  } catch (e) {
    message.error(e?.response?.data?.msg || '操作失败')
  }
}
const doRedirect = async () => { await api.provisionRedirect(currentId(), { target_url: '' }); message.success('301 已触发'); await load() }
const doHub = async () => { await api.dispatchHubJob(currentId(), { job_type: 'create_env', execute_now: true }); message.success('Hub 任务已触发'); await load() }
const doWoo = async () => { await api.importWoo(currentId()); message.success('Woo 导入已触发'); await load() }
const doRandomAssignProducts = async () => { await shopifyApi.randomAssign({ site_id: currentId(), count: assignProductCount.value || 6 }); message.success('已随机分配产品'); await load() }
const openAssignDialog = async () => { gmailVisible.value = true; await loadGmailList() }
const loadGmailList = async () => {
  gmailRows.value = (await gmailApi.getList({ page: 1, page_size: 50, username: gmailQuery.username, status: gmailQuery.status })).data || []
}
const assignGmail = async (gmailId) => {
  await gmailApi.assign({ gmail_id: gmailId, site_id: currentId() })
  message.success('Gmail 分配成功')
  gmailVisible.value = false
  await load()
}
const gmailColumns = [
  { title: '序号', key: 'index', width: 50, align: 'center', render: (_, index) => index + 1 },
  { title: 'Username', key: 'username' },
  { title: 'Password', key: 'password' },
  { title: 'Full Name', key: 'full_name' },
  { title: 'Recovery Email', key: 'recovery_email' },
  { title: '状态', key: 'status' },
  { title: '分配站点', key: 'assigned_site_domain' },
  { title: '操作', key: 'actions', render: row => h(NButton, { size: 'small', type: 'primary', onClick: () => assignGmail(row.id) }, { default: () => '分配到当前站点' }) },
]
onMounted(load)
</script>
