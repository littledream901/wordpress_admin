<template>
  <AppPage :show-footer="false">
    <div flex-1>
      <!-- 欢迎区 -->
      <n-card rounded-10>
        <div flex items-center justify-between>
          <div flex items-center>
            <img rounded-full width="60" :src="userStore.avatar" />
            <div ml-10>
              <p text-20 font-semibold>{{ greeting }}</p>
              <p mt-5 text-14 op-60>{{ subtitle }}</p>
            </div>
          </div>
          <div flex items-center gap-20>
            <n-tag v-if="agentOnline !== null" :type="agentOnline ? 'success' : 'default'" size="small" round :bordered="false">
              <template #icon>
                <span class="agent-dot" :class="agentOnline ? 'agent-online' : 'agent-offline'" />
              </template>
              Agent {{ agentOnline ? '在线' : '离线' }}
            </n-tag>
            <span text-14 op-40>{{ today }}</span>
          </div>
        </div>
      </n-card>

      <!-- 核心统计 -->
      <n-grid :cols="6" :x-gap="14" mt-16 responsive="screen">
        <n-grid-item v-for="card in statCards" :key="card.label">
          <n-card class="stat-card" :bordered="false" hoverable @click="card.link && $router.push(card.link)">
            <div flex flex-col gap-6>
              <div flex items-center justify-between>
                <span text-13 op-50>{{ card.label }}</span>
                <TheIcon :icon="card.icon" :size="22" :color="card.color" />
              </div>
              <div flex items-baseline gap-6>
                <span text-26 font-bold style="line-height:1.2">{{ card.value ?? '-' }}</span>
                <span v-if="card.sub" text-12 op-40>{{ card.sub }}</span>
                <span v-if="card.trend" text-12 ml-4 :style="{ color: card.trend > 0 ? '#63e2b7' : '#e88080' }">
                  {{ card.trend > 0 ? '↑' : '↓' }} {{ Math.abs(card.trend) }}
                </span>
              </div>
            </div>
          </n-card>
        </n-grid-item>
      </n-grid>

      <!-- 快捷入口 -->
      <n-card title="快捷入口" size="small" mt-16 rounded-10>
        <n-grid :cols="4" :x-gap="16" :y-gap="16" responsive="screen">
          <n-grid-item v-for="item in shortcuts" :key="item.path">
            <n-card size="small" hoverable class="shortcut-card" @click="$router.push(item.path)">
              <div flex items-center gap-12>
                <div class="shortcut-icon" :style="{ background: item.bg }">
                  <TheIcon :icon="item.icon" size="24" :color="item.color" />
                </div>
                <div>
                  <p text-15 font-semibold>{{ item.title }}</p>
                  <p text-12 op-50 mt-2>{{ item.desc }}</p>
                </div>
              </div>
            </n-card>
          </n-grid-item>
        </n-grid>
      </n-card>

      <!-- 1Panel 服务器监控 -->
      <n-card title="1Panel 服务器" size="small" mt-16 rounded-10>
        <template #header-extra>
          <n-button text type="primary" size="small" @click="loadOnePanel()">
            刷新
          </n-button>
        </template>
        <n-empty v-if="onePanelServers.length === 0 && !onePanelLoading" description="暂无 1Panel 服务器" size="small" />
        <n-skeleton v-if="onePanelLoading" :repeat="2" text />
        <div v-else flex flex-wrap gap-16>
          <div v-for="srv in onePanelServers" :key="srv.provider_id" class="onepanel-card">
            <!-- 头部 -->
            <div flex items-center justify-between mb-10>
              <div flex items-center gap-8>
                <span class="status-dot" :class="srv.status === 'ok' ? 'agent-online' : 'agent-offline'" />
                <span text-14 font-semibold>{{ srv.provider_name }}</span>
              </div>
              <n-tag :type="srv.status === 'ok' ? 'success' : 'default'" size="tiny" :bordered="false">
                {{ srv.status === 'ok' ? '在线' : srv.status }}
              </n-tag>
            </div>
            <div flex items-center gap-20 mb-12 text-12 op-60>
              <span>{{ srv.hostname || '-' }}</span>
              <span>{{ srv.os || '' }}</span>
            </div>

            <!-- 网站数 -->
            <div flex items-center justify-between mb-10>
              <span text-12 op-60>网站</span>
              <span text-14 font-bold>{{ srv.website_count ?? 0 }}</span>
            </div>

            <!-- 内存 -->
            <div mb-8>
              <div flex justify-between text-12 op-60 mb-4>
                <span>内存</span>
                <span>{{ formatBytes(srv.memory_used) }} / {{ formatBytes(srv.memory_total) }}</span>
              </div>
              <div class="progress-track">
                <div
                  class="progress-fill"
                  :style="{ width: `${Math.min(srv.memory_percent ?? 0, 100)}%`, background: progressColor(srv.memory_percent) }"
                />
              </div>
            </div>

            <!-- 硬盘 -->
            <div>
              <div flex justify-between text-12 op-60 mb-4>
                <span>硬盘 {{ srv._mainDisk ? srv._mainDisk.path : '' }}</span>
                <span>{{ formatBytes(srv._mainDisk?.used) }} / {{ formatBytes(srv._mainDisk?.total) }}</span>
              </div>
              <div class="progress-track">
                <div
                  class="progress-fill"
                  :style="{ width: `${Math.min(srv._mainDisk?.percent ?? 0, 100)}%`, background: progressColor(srv._mainDisk?.percent) }"
                />
              </div>
            </div>
          </div>
        </div>
      </n-card>
    </div>
  </AppPage>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { NCard, NGrid, NGridItem, NTag, NButton, NEmpty, NSkeleton } from 'naive-ui'
import TheIcon from '@/components/icon/TheIcon.vue'
import { useUserStore } from '@/store'
import api from '@/api'
import providerApi from '@/api/configProvider'
import shopifyApi from '@/api/shopify'
import sitePipelineApi from '@/api/site-pipeline'
import onepanelMonitorApi from '@/api/onepanel-monitor'

defineOptions({ name: '工作台' })

const userStore = useUserStore()

// 实时日期
const today = computed(() => {
  const d = new Date()
  const weekMap = ['日', '一', '二', '三', '四', '五', '六']
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 星期${weekMap[d.getDay()]}`
})

// 实时小时（响应式）
const currentHour = computed(() => new Date().getHours())

// 问候语
const greeting = computed(() => {
  const h = currentHour.value
  if (h < 6) return '夜深了，注意休息'
  if (h < 12) return '早上好，开启新的一天'
  if (h < 18) return '下午好，工作顺利'
  return '晚上好，今天辛苦了'
})

// 副标题
const subtitle = computed(() => {
  const h = currentHour.value
  if (h < 6) return '夜深人静，适合思考'
  if (h < 12) return '一日之计在于晨'
  if (h < 18) return '专注当下，高效产出'
  return '回顾今日，规划明天'
})

// ─── 统计卡片 ───
const stats = ref({ providers: 0, accounts: 0, products: 0, sites: 0 })

const statCards = computed(() => [
  { label: '流水线站点', value: stats.value.sites, icon: 'material-symbols:dns', color: '#e88080', link: '/site-pipeline/site-list' },
{ label: '配置 Provider', value: stats.value.providers, icon: 'material-symbols:settings', color: '#63e2b7', link: '/config/manage' },
  { label: '托管账号', value: stats.value.accounts, icon: 'material-symbols:group', color: '#70c0e8', link: '/config/accounts' },
  { label: 'Shopify 产品', value: stats.value.products, icon: 'material-symbols:shopping-cart', color: '#f0a020', link: '/shopify/product-list' },
  { label: 'Hub 环境', value: '-', icon: 'material-symbols:memory', color: '#a78bfa', link: '/site-pipeline/hub-dispatch', sub: '查询中' },
  { label: 'Gmail 邮箱', value: '-', icon: 'material-symbols:mail', color: '#38bdf8', link: '/gmail/account-list', sub: '查询中' },
])

// ─── Agent 状态 ───
const agentOnline = ref(null)

// ─── 快捷入口 ───
const shortcuts = [
  { title: '域名重定向', desc: '域名 301 重定向配置', path: '/site-pipeline/site-list', icon: 'material-symbols:swap-horiz', color: '#f0a020', bg: 'rgba(240,160,32,.12)' },
  { title: 'Feed 管理', desc: '数据源上传与 Feed 生成', path: '/site-pipeline/feed-manager', icon: 'material-symbols:rss-feed', color: '#a3a3a3', bg: 'rgba(163,163,163,.12)' },
  { title: 'Hub 调度', desc: '浏览器环境创建与管理', path: '/site-pipeline/hub-dispatch', icon: 'material-symbols:memory', color: '#e88080', bg: 'rgba(232,128,128,.12)' },
  { title: '站点流水线', desc: '独立站部署流水线管理', path: '/site-pipeline/site-list', icon: 'material-symbols:cloud-done', color: '#a78bfa', bg: 'rgba(167,139,250,.12)' },
  { title: '配置中心', desc: '管理 Provider 和配置项', path: '/config/manage', icon: 'material-symbols:settings', color: '#63e2b7', bg: 'rgba(99,226,183,.12)' },
  { title: '账号管理', desc: '管理账号密码与 Provider 绑定', path: '/config/accounts', icon: 'material-symbols:group', color: '#70c0e8', bg: 'rgba(112,192,232,.12)' },
  { title: '域名管理', desc: '域名解析与 DNS 配置', path: '/config/manage', icon: 'material-symbols:language', color: '#f472b6', bg: 'rgba(244,114,182,.12)' },
  { title: 'Gmail 邮箱', desc: '批量邮箱管理', path: '/gmail/account-list', icon: 'material-symbols:mail', color: '#38bdf8', bg: 'rgba(56,189,248,.12)' },

]

// ─── 1Panel 监控 ───
const onePanelServers = ref([])
const onePanelLoading = ref(false)

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 MB'
  const gb = bytes / (1024 * 1024 * 1024)
  if (gb >= 1) return gb.toFixed(1) + ' GB'
  return (bytes / (1024 * 1024)).toFixed(0) + ' MB'
}

function progressColor(pct) {
  if (!pct || pct < 60) return '#63e2b7'
  if (pct < 85) return '#f0a020'
  return '#e88080'
}

async function loadOnePanel() {
  onePanelLoading.value = true
  try {
    const res = await onepanelMonitorApi.getOnepanelMonitor({ refresh: true })
    const list = res?.data || []
    onePanelServers.value = list.map(srv => ({
      ...srv,
      _mainDisk: (srv.disks || []).find(d => d.path === '/' || d.path === '/opt') || (srv.disks || [])[0],
    }))
  } catch { /* ignore */ }
  onePanelLoading.value = false
}

// ─── 数据加载 ───
async function loadStats() {
  const [providerRes, accountRes, productRes, siteRes] = await Promise.allSettled([
    providerApi.getProviders({}),
    api.getAccountList({ page_size: 1 }),
    shopifyApi.getProductList({ page: 1, page_size: 1 }),
    sitePipelineApi.getSiteList({ page_size: 1 }),
  ])
  if (providerRes.status === 'fulfilled') stats.value.providers = providerRes.value?.total ?? 0
  if (accountRes.status === 'fulfilled') stats.value.accounts = accountRes.value?.total ?? 0
  if (productRes.status === 'fulfilled') stats.value.products = productRes.value?.total ?? 0
  if (siteRes.status === 'fulfilled') stats.value.sites = siteRes.value?.total ?? 0
}

async function loadAgents() {
  try {
    const res = await sitePipelineApi.getAgentStatus()
    agentOnline.value = res?.data?.any_online ?? null
  } catch {
    agentOnline.value = null
  }
}

onMounted(() => {
  loadStats()
  loadAgents()
  loadOnePanel()
})
</script>

<style scoped>
.stat-card {
  border-radius: 10px;
  transition: transform 0.2s;
  cursor: pointer;
}
.stat-card:hover {
  transform: translateY(-2px);
}

.shortcut-card {
  border-radius: 10px;
  transition: all 0.2s;
}
.shortcut-card:hover {
  transform: translateY(-2px);
}

.shortcut-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

/* Agent 状态指示灯 */
.agent-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 2px;
}
.agent-online {
  background: #63e2b7;
  box-shadow: 0 0 6px rgba(99, 226, 183, 0.5);
}
.agent-offline {
  background: #999;
}

/* 1Panel 服务器卡片 */
.onepanel-card {
  width: 300px;
  background: rgba(255,255,255,.03);
  border-radius: 10px;
  padding: 16px;
  flex-shrink: 0;
}
.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.progress-track {
  height: 6px;
  background: rgba(255,255,255,.08);
  border-radius: 3px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.6s ease;
}
</style>
