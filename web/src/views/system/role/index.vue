<script setup>
import { h, computed, nextTick, onMounted, reactive, ref, resolveDirective, watch, withDirectives } from 'vue'
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
const queryItems = reactive({})
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
        apiPrefix: '', // 从第一个子节点的 API path 提取英文模块前缀
        children: [],
      }
    }

    // 从 API path 提取英文模块前缀：/api/v1/site-pipeline/site/list → site-pipeline
    if (!groupedData[groupKey].apiPrefix) {
      const parts = item['path'].replace(/^\//, '').split('/')
      if (parts.length >= 3 && parts[0] === 'api' && parts[1] === 'v1') {
        groupedData[groupKey].apiPrefix = parts[2]
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

// 计算 API 分组在菜单树中的顺序索引（深度优先遍历，合并父子路径匹配）
function computeApiGroupOrder(nodes, apiSummary, apiPrefix = '') {
  let order = 0
  function walk(list, parentPath = '') {
    for (const node of list) {
      const fullPath = parentPath ? parentPath + '/' + node.path : node.path
      if (matchMenuToApiGroup(fullPath, apiSummary, apiPrefix)) return order
      order++
      if (node.children?.length) {
        const found = walk(node.children, node.path)
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
    return computeApiGroupOrder(menuOption.value, a.summary, a.apiPrefix) - computeApiGroupOrder(menuOption.value, b.summary, b.apiPrefix)
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

// 菜单 → API 级联：勾选/取消菜单时自动同步 API（及按钮）
// 匹配规则（按优先级）：
//   1. API path 英文模块前缀匹配（如 site-pipeline ↔ sitepipeline）
//   2. API 分组标签匹配（如 "站点流水线" 含中文时回退）
function matchMenuToApiGroup(menuPath, apiGroupSummary, apiPrefix = '') {
  if (!menuPath) return false
  const menuSegs = menuPath.toLowerCase().split('/').filter(Boolean)

  // 优先：用英文模块前缀匹配（最精确）
  const cleanPrefix = apiPrefix.replace(/[-_]/g, '').toLowerCase()
  if (cleanPrefix && cleanPrefix.length >= 3) {
    for (const seg of menuSegs.reverse()) {
      const cleanSeg = seg.replace(/[-_]/g, '')
      if (cleanSeg.length < 3) continue
      if (cleanSeg.includes(cleanPrefix) || cleanPrefix.includes(cleanSeg)) return true
    }
  }

  // 回退：用 API 分组标签匹配
  const apiClean = (apiGroupSummary || '').toLowerCase().replace(/[-_]/g, '')
  if (!apiClean) return false
  for (const seg of menuSegs.reverse()) {
    const cleanSeg = seg.replace(/[-_]/g, '')
    if (cleanSeg.length < 3) continue
    if (apiClean.includes(cleanSeg)) return true
  }
  return false
}

// 初始化跳过标志（打开抽屉时跳过 watch 初始触发）
let _skipMenuWatch = false

// 菜单 → API 级联：勾选/取消菜单时自动同步 API
watch(menu_ids, (newIds, oldIds) => {
  if (_skipMenuWatch || !apiOption.value.length) return

  const addedIds = newIds.filter((id) => !oldIds.includes(id))
  const removedIds = oldIds.filter((id) => !newIds.includes(id))

  // 收集所有需要添加的 API（先收集，最后一次性赋值）
  const addSet = new Set(api_ids.value)
  for (const menuId of addedIds) {
    const menuNode = findMenuNode(menuOption.value, menuId)
    if (!menuNode) continue
    // 仅对叶子菜单节点（无子节点）触发 API 级联
    if (menuNode.children && menuNode.children.length > 0) continue
    // 拼接父菜单路径用于匹配（父路径 + 自身路径覆盖更多前缀段）
    const parentNode = findParentNode(menuOption.value, menuId)
    const matchPath = parentNode ? parentNode.path + '/' + menuNode.path : menuNode.path
    // 遍历所有 API 分组，添加所有匹配的（同一模块可能有多个 tag）
    for (const group of apiOption.value) {
      if (matchMenuToApiGroup(matchPath, group.summary, group.apiPrefix)) {
        group.children.forEach((c) => addSet.add(c.unique_id))
      }
    }
  }

  // 收集需要移除的 API
  const removeSet = new Set()
  for (const menuId of removedIds) {
    const menuNode = findMenuNode(menuOption.value, menuId)
    if (!menuNode) continue
    if (menuNode.children && menuNode.children.length > 0) continue
    const menuParent = findParentNode(menuOption.value, menuId)
    const menuMatchPath = menuParent ? menuParent.path + '/' + menuNode.path : menuNode.path
    const stillChecked = newIds.some((id) => {
      const node = findMenuNode(menuOption.value, id)
      if (!node) return false
      const nodeParent = findParentNode(menuOption.value, id)
      const nodeMatchPath = nodeParent ? nodeParent.path + '/' + node.path : node.path
      for (const group of apiOption.value) {
        if (
          matchMenuToApiGroup(nodeMatchPath, group.summary, group.apiPrefix) &&
          matchMenuToApiGroup(menuMatchPath, group.summary, group.apiPrefix)
        ) {
          return true
        }
      }
      return false
    })
    if (!stillChecked) {
      for (const group of apiOption.value) {
        if (matchMenuToApiGroup(menuMatchPath, group.summary, group.apiPrefix)) {
          group.children.forEach((c) => removeSet.add(c.unique_id))
        }
      }
    }
  }

  // 一次性应用（先添加再移除，移除优先级高于添加）
  if (removeSet.size > 0) {
    removeSet.forEach((id) => addSet.delete(id))
  }
  api_ids.value = [...addSet]
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

// 查找菜单节点的父节点
function findParentNode(nodes, childId, parent = null) {
  for (const node of nodes) {
    if (node.children && node.children.length > 0) {
      for (const child of node.children) {
        if (child.id === childId) return node
      }
      const found = findParentNode(node.children, childId, node)
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
                  // 跳过 menu_ids watch 初始触发，直接设置为服务端值
                  _skipMenuWatch = true
                  api_ids.value = (roleAuthorizedResponse.data.apis || []).map(
                    (v) => v.method.toLowerCase() + v.path
                  )
                  menu_ids.value = (roleAuthorizedResponse.data.menus || []).map((v) => v.id)
                  await nextTick()
                  _skipMenuWatch = false

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
      <div style="margin-top: 12px; font-size: 12px; color: #999; line-height: 1.5;">
        全局默认值。若在"设置权限 → 数据权限"中配置了分模块权限，则以模块配置为准。
      </div>
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
          <NTabPane name="data_scope" tab="数据权限" display-directive="show">
            <div style="font-size: 12px; color: #999; margin-bottom: 12px;">
              按业务模块的独立权限配置，优先级高于角色编辑中的全局默认值。未配置的模块将回退到全局默认。
            </div>
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
