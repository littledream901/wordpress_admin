<template>
  <n-date-picker
    :value="modelValue"
    type="daterange"
    clearable
    placeholder="创建时间"
    style="width: 240px"
    format="yyyy-MM-dd"
    value-format="yyyy-MM-dd"
    :shortcuts="shortcuts"
    @update:value="onChange"
  />
</template>

<script setup>
const props = defineProps({
  modelValue: { type: Array, default: null },
})

const emit = defineEmits(['update:modelValue', 'change'])

function formatDateVal(v) {
  if (!v) return ''
  const d = new Date(typeof v === 'number' ? v : v)
  if (isNaN(d.getTime())) return ''
  const offset = d.getTimezoneOffset()
  const local = new Date(d.getTime() - offset * 60 * 1000)
  return local.toISOString().slice(0, 10)
}

const shortcuts = {
  '今天': (() => {
    const d = new Date()
    return [d.getTime(), d.getTime()]
  })(),
  '昨天': (() => {
    const d = new Date()
    d.setDate(d.getDate() - 1)
    return [d.getTime(), d.getTime()]
  })(),
  '最近三天': (() => {
    const end = new Date()
    const start = new Date()
    start.setDate(start.getDate() - 2)
    return [start.getTime(), end.getTime()]
  })(),
  '最近七天': (() => {
    const end = new Date()
    const start = new Date()
    start.setDate(start.getDate() - 6)
    return [start.getTime(), end.getTime()]
  })(),
}

function onChange(val) {
  emit('update:modelValue', val)
  if (val && val.length === 2) {
    emit('change', formatDateVal(val[0]), formatDateVal(val[1]))
  } else {
    emit('change', '', '')
  }
}
</script>
