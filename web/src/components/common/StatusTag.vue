<template>
  <n-tag :type="tagType" :size="size" :bordered="bordered" :round="round">
    {{ label }}
  </n-tag>
</template>

<script setup>
import { computed } from 'vue'
import { NTag } from 'naive-ui'

const props = defineProps({
  /** 状态值 */
  status: { type: String, required: true },
  /**
   * 状态映射表: { 状态值: { type: 'success'|'info'|'warning'|'error'|'default', label: '显示文本' } }
   * 不传则原样展示 status，type 默认为 'default'
   */
  statusMap: { type: Object, default: () => ({}) },
  /** 尺寸 */
  size: { type: String, default: 'small' },
  /** 是否显示边框 */
  bordered: { type: Boolean, default: false },
  /** 是否圆角 */
  round: { type: Boolean, default: false },
})

const tagType = computed(() => props.statusMap[props.status]?.type || 'default')
const label = computed(() => props.statusMap[props.status]?.label || props.status)
</script>
