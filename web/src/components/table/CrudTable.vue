<template>
  <div v-bind="$attrs">
    <!-- 搜索卡片 -->
    <n-card v-if="$slots.queryBar" size="small" rounded-10 mb-30>
      <div style="display:flex; align-items:center; flex-wrap:wrap; width:100%; gap: 8px">
        <n-space align="center" :wrap="false">
          <slot name="queryBar" />
          <n-button type="primary" @click="handleSearch">搜索</n-button>
          <n-button secondary @click="handleReset">重置</n-button>
        </n-space>
        <n-space v-if="$slots.queryBarActions" align="center" :wrap="false">
          <slot name="queryBarActions" />
        </n-space>
        <n-button text title="刷新" @click="handleRefresh" style="margin-left:auto; flex-shrink:0">
          <template #icon>
            <TheIcon icon="mdi:refresh" :size="18" />
          </template>
        </n-button>
      </div>
    </n-card>

    <n-data-table
      :remote="remote"
      :loading="loading"
      :columns="columns"
      :data="tableData"
      :scroll-x="scrollX"
      :row-key="(row) => row[rowKey]"
      :row-props="rowProps"
      :pagination="isPagination ? pagination : false"
      @update:checked-row-keys="onChecked"
      @update:page="onPageChange"
    />
  </div>
</template>

<script setup>
import { ref, reactive, nextTick, onMounted } from 'vue'
import TheIcon from '@/components/icon/TheIcon.vue'

const props = defineProps({
  /**
   * @remote true: 后端分页  false： 前端分页
   */
  remote: {
    type: Boolean,
    default: true,
  },
  /**
   * @remote 是否分页
   */
  isPagination: {
    type: Boolean,
    default: true,
  },
  scrollX: {
    type: Number,
    default: 450,
  },
  rowKey: {
    type: String,
    default: 'id',
  },
  rowProps: {
    type: Function,
    default: undefined,
  },
  columns: {
    type: Array,
    required: true,
  },
  /** queryBar中的参数 */
  queryItems: {
    type: Object,
    default() {
      return {}
    },
  },
  /** 补充参数（可选） */
  extraParams: {
    type: Object,
    default() {
      return {}
    },
  },
  /**
   * 默认每页条数
   */
  pageSize: {
    type: Number,
    default: 10,
  },
  showSizePicker: {
    type: Boolean,
    default: true,
  },
  /**
   * ! 约定接口入参出参
   * * 分页模式需约定分页接口入参
   *    @page_size 分页参数：一页展示多少条，默认10
   *    @page   分页参数：页码，默认1
   */
  getData: {
    type: Function,
    required: true,
  },
})

const emit = defineEmits(['update:queryItems', 'onChecked', 'onDataChange'])
const loading = ref(false)

// 深拷贝初始 queryItems，确保快照不受外部修改影响
const initQuery = JSON.parse(JSON.stringify(props.queryItems))

const tableData = ref([])
const pagination = reactive({
  page: 1,
  page_size: props.pageSize,
  pageSizes: [50, 100, 200,500],
  showSizePicker: props.showSizePicker,
  prefix({ itemCount }) {
    return `共 ${itemCount} 条`
  },
  onChange: (page) => {
    pagination.page = page
  },
  onUpdatePageSize: (pageSize) => {
    pagination.page_size = pageSize
    pagination.page = 1
    handleQuery()
  },
})

async function handleQuery() {
  if (loading.value) return
  try {
    loading.value = true
    let paginationParams = {}
    // 如果非分页模式或者使用前端分页,则无需传分页参数
    if (props.isPagination && props.remote) {
      paginationParams = { page: pagination.page, page_size: pagination.page_size }
    }
    const { data, total } = await props.getData({
      ...props.queryItems,
      ...props.extraParams,
      ...paginationParams,
    })
    tableData.value = data
    pagination.itemCount = total || 0
  } catch (error) {
    tableData.value = []
    pagination.itemCount = 0
  } finally {
    emit('onDataChange', tableData.value)
    loading.value = false
  }
}

function handleSearch() {
  pagination.page = 1
  handleQuery()
}

function handleReset() {
  emit('update:queryItems', JSON.parse(JSON.stringify(initQuery)))
  pagination.page = 1
  nextTick(() => handleQuery())
}

function handleRefresh() {
  if (loading.value) return
  handleQuery()
}

function onPageChange(currentPage) {
  pagination.page = currentPage
  if (props.remote) {
    handleQuery()
  }
}

function onChecked(rowKeys) {
  if (props.columns.some((item) => item.type === 'selection')) {
    emit('onChecked', rowKeys)
  }
}

onMounted(() => {
  nextTick(() => handleSearch())
})

defineExpose({
  handleSearch,
  handleRefresh,
  handleReset,
  tableData,
})
</script>
