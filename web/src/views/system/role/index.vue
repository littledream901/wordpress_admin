<script setup>
import { h, computed, onMounted, ref, resolveDirective, watch, withDirectives } from 'vue'
import {
  NButton,
  NForm,
  NFormItem,
  NInput,
  NPopconfirm,
  NSelect,
  NSpace,
  NTag,
  NTree,
  NTreeSelect,
  NDrawer,
  NDrawerContent,
  NTabs,
  NTabPane,
  NGrid,
  NGi,
} from 'naive-ui'

import CommonPage from '@/components/page/CommonPage.vue'
import CrudModal from '@/components/table/CrudModal.vue'
import CrudTable from '@/components/table/CrudTable.vue'

import { formatDate, renderIcon } from '@/utils'
import { useCRUD } from '@/composables'
import api from '@/api'
import TheIcon from '@/components/icon/TheIcon.vue'

defineOptions({ name: '角色管理' })

const $table = ref(null)
const queryItems = ref({})
const vPermission = resolveDirective('permission')

const {
  modalVisible,
  modalAction,
  modalTitle,
  modalLoading,
  handleAdd,
  handleDelete,
  handleEdit,
  handleSave,
  modalForm,
  modalFormRef,
} = useCRUD({
  name: '角色',
  initForm: { data_scope: 3 },
  doCreate: api.createRole,
  doDelete: api.deleteRole,
  doUpdate: api.updateRole,
  refresh: () => $table.value?.handleSearch(),
})

// 部门树（用于自定义部门选择）
const deptTreeOptions = ref([])

// 权限设置抽屉相关
const pattern = ref('')
const menuOption = ref([])
const active = ref(false)
const menu_ids = ref([])
const role_id = ref(0)
const rawApiData = ref([])
const api_ids = ref([])
const apiTree = ref(null)

// 抽屉内的数据权限配置
const dataScopeOptions = [
  { label: '全部数据权限', value: 0 },
  { label: '本部门及以下数据', value: 1 },
  { label: '仅本部门数据', value: 2 },
  { label: '仅本人数据', value: 3 },
  { label: '自定义部门', value: 4 },
]

// 业务模块标识 → 显示名称（与后端 RESOURCE_LABELS 同步）
const RESOURCE_LABELS = {
  site: '站点管理',
  account: '账户配置',
  gmail: 'Gmail',
  shopify: 'Shopify',
  operation: '操作任务',
  import: '导入管理',
}

// 按业务模块的数据权限配置
const drawerDataScopes = ref(
  Object.entries(RESOURCE_LABELS).map(([resource, label]) => ({
    resource,
    resource_label: label,
    data_scope: 3,
    custom_dept_ids: [],
  }))
)

function buildApiTree(data) {
  // 按 tags（模块）分组，每组用 path 作为子节点
  const groupedData = {}
  data.forEach((item) => {
    const tag = item['tags'] || 'default'
    const groupLabel = tag.charAt(0).toUpperCase() + tag.slice(1)
    const groupKey = tag
    const unique_id = item['method'].toLowerCase() + item['path']

    if (!(groupKey in groupedData)) {
      groupedData[groupKey] = {
        unique_id: groupKey,
        path: groupKey,
        summary: groupLabel,
        children: [],
      }
    }

    groupedData[groupKey].children.push({
      id: item['id'],
      path: item['path'],
      method: item['method'],
      summary: item['summary'],
      unique_id: unique_id,
      is_button: item['is_button'] || false,
    })
  })
  return Object.values(groupedData)
}

// 计算 API 分组在菜单树中的顺序索引（深度优先遍历）
function computeApiGroupOrder(nodes, apiSummary) {
  let order = 0
  function walk(list) {
    for (const node of list) {
      if (matchMenuToApiGroup(node.path, apiSummary)) return order
      order++
      if (node.children?.length) {
        const found = walk(node.children)
        if (found !== -1) return found
      }
    }
    return -1
  }
  const result = walk(nodes)
  return result === -1 ? 9999 : result
}

// 接口权限树：按菜单顺序排序分组
const apiOption = computed(() => {
  if (!rawApiData.value.length) return []
  const tree = buildApiTree(rawApiData.value)
  if (!menuOption.value.length) return tree
  tree.sort((a, b) => {
    return computeApiGroupOrder(menuOption.value, a.summary) - computeApiGroupOrder(menuOption.value, b.summary)
  })
  return tree
})

// 按钮权限树：仅包含 is_button=True 的 API（继承 apiOption 排序）
const buttonApiOption = computed(() => {
  return apiOption.value
    .map((group) => {
      const buttonChildren = group.children.filter((child) => child.is_button)
      if (buttonChildren.length === 0) return null
      return { ...group, children: buttonChildren }
    })
    .filter(Boolean)
})

// 递归收集菜单树下所有叶子节点 id
function collectLeafMenuIds(nodes) {
  const ids = []
  for (const node of nodes) {
    if (node.children && node.children.length > 0) {
      ids.push(...collectLeafMenuIds(node.children))
    } else {
      ids.push(node.id)
    }
  }
  return ids
}

// 菜单 → API 级联：勾选菜单时自动勾选对应模块的 API（及按钮）
// 根据菜单 path 的最后一段匹配 API 路径前缀
function matchMenuToApiGroup(menuPath, apiGroupSummary) {
  if (!menuPath || !apiGroupSummary) return false
  // 从菜单 path 提取关键词（如 system/user → user, site-pipeline/site-list → site-pipeline,site-list）
  const menuSegs = menuPath.toLowerCase().split('/')
  const apiSummaryLower = apiGroupSummary.toLowerCase()
  // 尝试每个菜单路径段（从后往前）去匹配 API 路径
  for (const seg of menuSegs.reverse()) {
    if (!seg) continue
    // 去掉连字符：site-list → sitelist, SitePipeline → sitepipeline
    const cleanSeg = seg.replace(/[-_]/g, '')
    const cleanSummary = apiSummaryLower.replace(/[-_]/g, '')
    if (cleanSummary.includes(cleanSeg) || cleanSeg.includes(cleanSummary)) return true
  }
  return false
}

watch(menu_ids, (newIds, oldIds) => {
  if (!apiOption.value.length) return

  const addedIds = newIds.filter((id) => !oldIds.includes(id))
  const removedIds = oldIds.filter((id) => !newIds.includes(id))

  for (const menuId of addedIds) {
    const menuNode = findMenuNode(menuOption.value, menuId)
    if (!menuNode) continue
    for (const group of apiOption.value) {
      if (matchMenuToApiGroup(menuNode.path, group.summary)) {
        const childIds = group.children.map((c) => c.unique_id)
        api_ids.value = [...new Set([...api_ids.value, ...childIds])]
        break
      }
    }
  }

  for (const menuId of removedIds) {
    const menuNode = findMenuNode(menuOption.value, menuId)
    if (!menuNode) continue
    const stillChecked = newIds.some((id) => {
      const node = findMenuNode(menuOption.value, id)
      if (!node) return false
      for (const group of apiOption.value) {
        if (
          matchMenuToApiGroup(node.path, group.summary) &&
          matchMenuToApiGroup(menuNode.path, group.summary)
        ) {
          return true
        }
      }
      return false
    })
    if (!stillChecked) {
      for (const group of apiOption.value) {
        if (matchMenuToApiGroup(menuNode.path, group.summary)) {
          const childIds = new Set(group.children.map((c) => c.unique_id))
          api_ids.value = api_ids.value.filter((id) => !childIds.has(id))
          break
        }
      }
    }
  }
})

// 递归查找菜单节点
function findMenuNode(nodes, id) {
  for (const node of nodes) {
    if (node.id === id) return node
    if (node.children && node.children.length > 0) {
      const found = findMenuNode(node.children, id)
      if (found) return found
    }
  }
  return null
}

onMounted(() => {
  $table.value?.handleSearch()
  // 加载部门树
  api.getDepts().then((res) => {
    deptTreeOptions.value = res.data || []
  })
})

const columns = [
  {
    title: '角色名',
    key: 'name',
    width: 80,
    align: 'center',
    ellipsis: { tooltip: true },
    render(row) {
      return h(NTag, { type: 'info' }, { default: () => row.name })
    },
  },
  {
    title: '数据权限',
    key: 'data_scope',
    width: 60,
    align: 'center',
    render(row) {
      const opt = dataScopeOptions.find((o) => o.value === row.data_scope)
      return h(NTag, { type: 'warning' }, { default: () => opt?.label || '未知' })
    },
  },
  {
    title: '角色描述',
    key: 'desc',
    width: 80,
    align: 'center',
  },
  {
    title: '创建日期',
    key: 'created_at',
    width: 60,
    align: 'center',
    render(row) {
      return h('span', formatDate(row.created_at))
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 80,
    align: 'center',
    fixed: 'right',
    render(row) {
      return [
        withDirectives(
          h(
            NButton,
            {
              size: 'small',
              type: 'primary',
              style: 'margin-right: 8px;',
              onClick: () => {
                handleEdit(row)
              },
            },
            {
              default: () => '编辑',
              icon: renderIcon('material-symbols:edit-outline', { size: 16 }),
            }
          ),
          [[vPermission, 'post/api/v1/role/update']]
        ),
        h(
          NPopconfirm,
          {
            onPositiveClick: () => handleDelete({ role_id: row.id }, false),
            onNegativeClick: () => {},
          },
          {
            trigger: () =>
              withDirectives(
                h(
                  NButton,
                  {
                    size: 'small',
                    type: 'error',
                    style: 'margin-right: 8px;',
                  },
                  {
                    default: () => '删除',
                    icon: renderIcon('material-symbols:delete-outline', { size: 16 }),
                  }
                ),
                [[vPermission, 'delete/api/v1/role/delete']]
              ),
            default: () => h('div', {}, '确定删除该角色吗?'),
          }
        ),
        withDirectives(
          h(
            NButton,
            {
              size: 'small',
              type: 'primary',
              onClick: async () => {
                try {
                  const [menusResponse, apisResponse, roleAuthorizedResponse] = await Promise.all([
                    api.getMenus({ page: 1, page_size: 9999 }),
                    api.getApis({ page: 1, page_size: 9999 }),
                    api.getRoleAuthorized({ id: row.id }),
                  ])

                  menuOption.value = menusResponse.data
                  rawApiData.value = apisResponse.data
                  menu_ids.value = (roleAuthorizedResponse.data.menus || []).map((v) => v.id)
                  api_ids.value = (roleAuthorizedResponse.data.apis || []).map(
                    (v) => v.method.toLowerCase() + v.path
                  )

                  // 填充数据权限配置
                  const apiDataScopes = roleAuthorizedResponse.data.data_scopes || []
                  if (apiDataScopes.length > 0) {
                    drawerDataScopes.value.forEach((ds) => {
                      const matched = apiDataScopes.find((s) => s.resource === ds.resource)
                      if (matched) {
                        ds.data_scope = matched.data_scope ?? 3
                        ds.custom_dept_ids = (matched.custom_depts || []).map((v) => v.id)
                      }
                    })
                  }

                  active.value = true
                  role_id.value = row.id
                } catch (error) {
                  console.error('Error loading data:', error)
                }
              },
            },
            {
              default: () => '设置权限',
              icon: renderIcon('material-symbols:edit-outline', { size: 16 }),
            }
          ),
          [[vPermission, 'get/api/v1/role/authorized']]
        ),
      ]
    },
  },
]

async function updateRoleAuthorized() {
  // 从 api_ids 构建 api_infos，确保按钮权限和接口权限的勾选都生效
  const apiInfos = api_ids.value.map((key) => {
    // key 格式: "get/api/v1/user/list" → method=GET, path=/api/v1/user/list
    const httpMethod = key.match(/^(get|post|put|delete|patch)/i)
    if (!httpMethod) return null
    const method = httpMethod[1].toUpperCase()
    const path = key.slice(httpMethod[1].length)
    return { path, method }
  }).filter(Boolean)

  const payload = {
    id: role_id.value,
    menu_ids: menu_ids.value,
    api_infos: apiInfos,
    data_scopes: drawerDataScopes.value.map((ds) => ({
      resource: ds.resource,
      data_scope: ds.data_scope,
      custom_dept_ids: ds.data_scope === 4 ? ds.custom_dept_ids : [],
    })),
  }

  const { code, msg } = await api.updateRoleAuthorized(payload)
  if (code === 200) {
    $message?.success('设置成功')
    // 刷新已授权数据
    const result = await api.getRoleAuthorized({ id: role_id.value })
    menu_ids.value = (result.data.menus || []).map((v) => v.id)
    api_ids.value = (result.data.apis || []).map((v) => v.method.toLowerCase() + v.path)
    // 刷新数据权限配置
    const scopes = result.data.data_scopes || []
    if (scopes.length > 0) {
      drawerDataScopes.value.forEach((ds) => {
        const matched = scopes.find((s) => s.resource === ds.resource)
        if (matched) {
          ds.data_scope = matched.data_scope ?? 3
          ds.custom_dept_ids = (matched.custom_depts || []).map((v) => v.id)
        }
      })
    }
  } else {
    $message?.error(msg)
  }
}
</script>

<template>
  <CommonPage show-footer title="角色列表">
    <template #action>
      <NButton v-permission="'post/api/v1/role/create'" type="primary" @click="handleAdd">
        <TheIcon icon="material-symbols:add" :size="18" class="mr-5" />新建角色
      </NButton>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="api.getRoleList"
    >
      <template #queryBar>
        <n-input v-model:value="queryItems.role_name" clearable placeholder="角色名" style="width: 180px" @keypress.enter="$table?.handleSearch()" />
      </template>
    </CrudTable>

    <!-- 新增/编辑 弹窗 -->
    <CrudModal
      v-model:visible="modalVisible"
      :title="modalTitle"
      :loading="modalLoading"
      @save="handleSave"
    >
      <NForm
        ref="modalFormRef"
        label-placement="left"
        label-align="left"
        :label-width="80"
        :model="modalForm"
        :disabled="modalAction === 'view'"
      >
        <NFormItem
          label="角色名"
          path="name"
          :rule="{
            required: true,
            message: '请输入角色名称',
            trigger: ['input', 'blur'],
          }"
        >
          <NInput v-model:value="modalForm.name" placeholder="请输入角色名称" />
        </NFormItem>
        <NFormItem label="角色描述" path="desc">
          <NInput v-model:value="modalForm.desc" placeholder="请输入角色描述" />
        </NFormItem>
        <NFormItem label="数据权限" path="data_scope">
          <NSelect
            v-model:value="modalForm.data_scope"
            :options="dataScopeOptions"
            placeholder="请选择数据权限范围"
          />
        </NFormItem>
      </NForm>
    </CrudModal>

    <!-- 权限设置抽屉 -->
    <NDrawer v-model:show="active" placement="right" :width="550">
      <NDrawerContent>
        <NGrid x-gap="24" cols="12">
          <NGi span="8">
            <NInput
              v-model:value="pattern"
              type="text"
              placeholder="筛选"
              style="flex-grow: 1"
            ></NInput>
          </NGi>
          <NGi offset="2">
            <NButton
              v-permission="'post/api/v1/role/authorized'"
              type="info"
              @click="updateRoleAuthorized"
              >确定</NButton
            >
          </NGi>
        </NGrid>
        <NTabs>
          <NTabPane name="menu" tab="菜单权限" display-directive="show">
            <NTree
              :data="menuOption"
              :checked-keys="menu_ids"
              :pattern="pattern"
              :show-irrelevant-nodes="false"
              key-field="id"
              label-field="name"
              checkable
              cascade
              :default-expand-all="true"
              :block-line="true"
              :selectable="false"
              @update:checked-keys="(v) => (menu_ids = v)"
            />
          </NTabPane>
          <NTabPane name="resource" tab="接口权限" display-directive="show">
            <NTree
              ref="apiTree"
              :data="apiOption"
              :checked-keys="api_ids"
              :pattern="pattern"
              :show-irrelevant-nodes="false"
              key-field="unique_id"
              label-field="summary"
              checkable
              :default-expand-all="true"
              :block-line="true"
              :selectable="false"
              cascade
              @update:checked-keys="(v) => (api_ids = v)"
            />
          </NTabPane>
          <NTabPane name="button" tab="按钮权限" display-directive="show">
            <NTree
              :data="buttonApiOption"
              :checked-keys="api_ids"
              :pattern="pattern"
              :show-irrelevant-nodes="false"
              key-field="unique_id"
              label-field="summary"
              checkable
              :default-expand-all="true"
              :block-line="true"
              :selectable="false"
              cascade
              @update:checked-keys="(v) => (api_ids = v)"
            />
          </NTabPane>
          <NTabPane name="data_scope" tab="数据权限" display-directive="show">
            <NForm label-placement="left" label-align="left" :label-width="100">
              <NFormItem
                v-for="ds in drawerDataScopes"
                :key="ds.resource"
                :label="ds.resource_label"
                :path="'data_scope_' + ds.resource"
              >
                <NSpace vertical style="width: 100%">
                  <NSelect
                    v-model:value="ds.data_scope"
                    :options="dataScopeOptions"
                    placeholder="请选择数据权限范围"
                  />
                  <NTreeSelect
                    v-if="ds.data_scope === 4"
                    v-model:value="ds.custom_dept_ids"
                    :options="deptTreeOptions"
                    key-field="id"
                    label-field="name"
                    multiple
                    placeholder="请选择自定义部门"
                    clearable
                    :default-expand-all="true"
                  />
                </NSpace>
              </NFormItem>
            </NForm>
          </NTabPane>
        </NTabs>
        <template #header> 设置权限 </template>
      </NDrawerContent>
    </NDrawer>
  </CommonPage>
</template>
