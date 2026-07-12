/**
 * 将 JSON 对象解析为树形节点数组，用于语法高亮渲染
 * @param {*} obj - 要解析的 JSON 值
 * @param {number} depth - 当前缩进深度
 * @returns {Array<{bracket?, key?, value?, rawType?, depth}>}
 */
export function buildJsonTree(obj, depth = 0) {
  const nodes = []
  if (Array.isArray(obj)) {
    nodes.push({ bracket: '[', depth })
    obj.forEach((item, idx) => {
      if (typeof item === 'object' && item !== null) {
        nodes.push({ bracket: '{', depth: depth + 1, key: `${idx}` })
        nodes.push(...buildJsonTree(item, depth + 1))
        nodes.push({ bracket: '}', depth: depth + 1 })
      } else {
        nodes.push({ key: `${idx}`, value: formatJsonValue(item), depth: depth + 1, rawType: typeof item })
      }
    })
    nodes.push({ bracket: ']', depth })
  } else if (typeof obj === 'object' && obj !== null) {
    nodes.push({ bracket: '{', depth })
    const keys = Object.keys(obj)
    keys.forEach(key => {
      const val = obj[key]
      if (typeof val === 'object' && val !== null) {
        nodes.push({ bracket: '{', depth: depth + 1, key })
        nodes.push(...buildJsonTree(val, depth + 2))
      } else {
        nodes.push({ key, value: formatJsonValue(val), depth: depth + 1, rawType: typeof val })
      }
    })
    nodes.push({ bracket: '}', depth })
  }
  return nodes
}

function formatJsonValue(val) {
  if (val === null) return 'null'
  if (typeof val === 'string') return `"${val}"`
  if (typeof val === 'boolean') return String(val)
  return String(val)
}

/**
 * 根据节点类型返回 CSS 类名
 */
export function jsonValueClass(node) {
  switch (node.rawType) {
    case 'string': return 'json-string'
    case 'number': return 'json-number'
    case 'boolean': return 'json-boolean'
    default:
      if (node.value === 'null') return 'json-null'
      return 'json-string'
  }
}

/**
 * 对 JSON 字符串进行语法高亮（HTML），用于 textarea 叠加高亮
 * @param {string} json - 原始 JSON 字符串
 * @returns {string} 带 <span class="json-xxx"> 的 HTML
 */
export function syntaxHighlight(json) {
  if (!json) return ''
  const escaped = json
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  return escaped.replace(
    /("(\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?|[\[\]{}])/g,
    (match) => {
      if (/^[\[\]{}]$/.test(match)) return `<span class="json-bracket">${match}</span>`
      let cls = 'json-number'
      if (/^"/.test(match)) {
        if (/:$/.test(match)) {
          return `<span class="json-key">${match.slice(0, -1)}</span><span class="json-colon">:</span>`
        }
        cls = 'json-string'
      } else if (/true|false/.test(match)) {
        cls = 'json-boolean'
      } else if (/null/.test(match)) {
        cls = 'json-null'
      }
      return `<span class="${cls}">${match}</span>`
    },
  )
}

/**
 * 注入 JSON 语法高亮全局样式（单例，多次调用只注入一次）
 * 页面 <style scoped> 无法覆盖 v-html 渲染的 span，需全局样式。
 */
export function injectJsonStyles() {
  if (document.getElementById('json-tree-styles')) return
  const style = document.createElement('style')
  style.id = 'json-tree-styles'
  style.textContent = `
.json-key   { color: #89b4fa; cursor: pointer; }
.json-colon { color: #a6adc8; }
.json-string { color: #a6e3a1; word-break: break-all; }
.json-number { color: #fab387; }
.json-boolean { color: #cba6f7; }
.json-null  { color: #f38ba8; font-style: italic; }
.json-bracket { color: #f9e2af; }
  `
  document.head.appendChild(style)
}
