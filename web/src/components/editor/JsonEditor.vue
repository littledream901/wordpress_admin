<template>
  <div class="json-editor-wrap">
    <div v-if="showToolbar" class="json-toolbar">
      <span v-if="errorMsg" class="json-err">{{ errorMsg }}</span>
      <span v-else class="json-hint">{{ hint || '编辑 JSON，Ctrl+Enter 保存' }}</span>
      <span class="json-lines">{{ lineCount }} 行</span>
    </div>
    <div
      ref="scrollRef"
      class="json-editor"
      :class="{ 'has-error': errorMsg }"
      :style="{ maxHeight: maxHeight + 'px', minHeight: minHeight + 'px' }"
    >
      <div class="json-inner" :style="{ minHeight: innerHeight + 'px' }">
        <div class="json-gutter">
          <div class="json-gutter-inner">
            <span v-for="i in lineCount" :key="i" class="json-gutter-ln">{{ i }}</span>
          </div>
        </div>
        <div class="json-editor-area">
          <pre class="json-highlight" aria-hidden="true" v-html="highlighted"></pre>
          <textarea
            ref="taRef"
            class="json-textarea"
            :value="modelValue"
            :placeholder="placeholder"
            :readonly="readonly"
            :disabled="disabled"
            :spellcheck="false"
            :style="{ height: innerHeight + 'px' }"
            @input="onInput"
            @blur="onBlur"
            @keydown="onKeydown"
          ></textarea>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { syntaxHighlight, injectJsonStyles } from '@/utils/jsonTree'

injectJsonStyles()

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '{"key": "value"}' },
  disabled: Boolean,
  readonly: Boolean,
  showToolbar: { type: Boolean, default: true },
  hint: { type: String, default: '' },
  maxHeight: { type: Number, default: 500 },
  minHeight: { type: Number, default: 120 },
  lineHeight: { type: Number, default: 24 },
  padding: { type: Number, default: 28 },
})

const emit = defineEmits(['update:modelValue', 'blur', 'change'])

const taRef = ref(null)
const errorMsg = ref('')
const lineCount = ref(1)

// ─── 语法高亮 ───
const highlighted = ref('')
function updateHighlight() {
  highlighted.value = syntaxHighlight(props.modelValue)
}

// ─── 内容实际高度 ───
const innerHeight = computed(() => {
  return Math.max(lineCount.value * props.lineHeight + props.padding, props.minHeight)
})

// ─── 输入处理 ───
function onInput(e) {
  const val = e.target.value
  emit('update:modelValue', val)
  updateHighlight()
  lineCount.value = val.split('\n').length || 1
  if (val.trim()) {
    try { JSON.parse(val); errorMsg.value = '' }
    catch (err) { errorMsg.value = err.message }
  } else {
    errorMsg.value = ''
  }
}

function onBlur() {
  emit('blur', props.modelValue)
}

function onKeydown(e) {
  if (e.ctrlKey && e.key === 'Enter') {
    e.preventDefault()
    emit('change', props.modelValue)
  }
  if (e.key === 'Tab') {
    e.preventDefault()
    const ta = e.target
    const start = ta.selectionStart
    const end = ta.selectionEnd
    const val = props.modelValue
    emit('update:modelValue', val.substring(0, start) + '  ' + val.substring(end))
    nextTick(() => { ta.selectionStart = ta.selectionEnd = start + 2 })
  }
}

// ─── 初始化 ───
watch(() => props.modelValue, (v) => {
  updateHighlight()
  lineCount.value = (v || '').split('\n').length || 1
}, { immediate: true })

onMounted(() => {
  updateHighlight()
  lineCount.value = props.modelValue.split('\n').length || 1
})
</script>

<style scoped>
.json-editor-wrap { width: 100%; margin-bottom: 8px; }

.json-toolbar {
  display: flex; align-items: center; gap: 12px;
  margin-bottom: 6px; font-size: 12px;
}
.json-err { color: #e5534b; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.json-hint { color: #7878a0; flex: 1; }
.json-lines { color: #585878; flex-shrink: 0; }

/* ── 外层滚动容器 ── */
.json-editor {
  border-radius: 8px;
  background: #1e1e2e;
  border: 1px solid #313244;
  overflow: auto;
}
.json-editor.has-error { border-color: #e5534b; }
.json-editor:focus-within { border-color: #89b4fa; }

/* ── 内部 flex 行 ── */
.json-inner { display: flex; }

/* ── 行号栏 ── */
.json-gutter {
  flex-shrink: 0;
  width: 52px;
  overflow: hidden;
  user-select: none;
  text-align: right;
  background: #181825;
  border-right: 1px solid #313244;
}
.json-gutter-inner { padding-top: 14px; }
.json-gutter-ln {
  display: block;
  height: 24px;
  line-height: 24px;
  padding-right: 12px;
  font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace;
  font-size: 14px;
  color: #585878;
}

/* ── 编辑区（pre 和 textarea 叠加） ── */
.json-editor-area {
  flex: 1;
  position: relative;
}

/* pre 和 textarea 共用字体/排版 ── */
.json-highlight,
.json-textarea {
  font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace;
  font-size: 14px;
  line-height: 24px;
  padding: 14px;
  margin: 0;
  border: none;
  white-space: pre;
  tab-size: 2;
}

/* ── 高亮层（底层） ── */
.json-highlight {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: 1;
  color: #cdd6f4;
  background: transparent;
}

/* ── 编辑层（顶层，透明文字） ── */
.json-textarea {
  display: block;
  position: relative;
  z-index: 2;
  width: 100%;
  color: transparent;
  caret-color: #f5e0dc;
  background: transparent;
  outline: none;
  resize: none;
  overflow: hidden;
}
.json-textarea::placeholder {
  color: #585878;
  font-style: italic;
}
.json-textarea::selection {
  background: rgba(137, 180, 250, 0.25);
}

@media (max-width: 640px) {
  .json-gutter { width: 40px; }
  .json-gutter-ln { font-size: 11px; padding-right: 8px; }
  .json-highlight, .json-textarea { font-size: 12px; padding: 10px; }
  .json-gutter-inner { padding-top: 10px; }
}
</style>
