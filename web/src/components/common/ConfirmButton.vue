<template>
  <n-popconfirm @positive-click="$emit('confirm')">
    <template #trigger>
      <n-button
        :type="type"
        :size="size"
        :loading="loading"
        :disabled="disabled || loading"
        v-bind="$attrs"
      >
        <slot>{{ btnText }}</slot>
      </n-button>
    </template>
    <slot name="content">{{ confirmText }}</slot>
  </n-popconfirm>
</template>

<script setup>
import { NButton, NPopconfirm } from 'naive-ui'

defineProps({
  /** 按钮文本 */
  btnText: { type: String, default: '删除' },
  /** 确认提示文本 */
  confirmText: { type: String, default: '确定执行此操作？' },
  /** 按钮类型 */
  type: { type: String, default: 'error' },
  /** 按钮尺寸 */
  size: { type: String, default: 'small' },
  /** 加载中 */
  loading: { type: Boolean, default: false },
  /** 禁用 */
  disabled: { type: Boolean, default: false },
})

defineEmits(['confirm'])
</script>
