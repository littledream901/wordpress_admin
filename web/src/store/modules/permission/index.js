import { defineStore } from 'pinia'
import { h } from 'vue'
import { basicRoutes, EMPTY_ROUTE, NOT_FOUND_ROUTE, vueModules } from '@/router/routes'
import Layout from '@/layout/index.vue'
import api from '@/api'

// * 后端路由相关函数
// 根据后端传来数据构建出前端路由

function getComponent(componentPath) {
  const key = `/src/views${componentPath}/index.vue`
  const mod = vueModules[key]
  if (mod) return mod
  // Fallback: 尝试扁平文件路径（例如 error-page/401.vue）
  const flatKey = `/src/views${componentPath}.vue`
  const flatMod = vueModules[flatKey]
  if (flatMod) return flatMod
  console.warn(`[Permission] Component not found in vueModules: ${key}`)
  return { render: () => h('div', { style: 'padding:40px;text-align:center;color:#999' }, `组件 ${componentPath} 未加载`) }
}

function buildRoutes(routes = []) {
  return routes.map((e) => {
    const route = {
      name: e.name,
      path: e.path,
      component: shallowRef(Layout),
      isHidden: e.is_hidden,
      redirect: e.redirect,
      meta: {
        title: e.name,
        icon: e.icon,
        order: e.order,
        keepAlive: e.keepalive,
      },
      children: [],
    }

    if (e.children && e.children.length > 0) {
      // 有子菜单
      route.children = e.children.map((e_child) => ({
        name: e_child.name,
        path: e_child.path,
        component: getComponent(e_child.component),
        isHidden: e_child.is_hidden,
        meta: {
          title: e_child.name,
          icon: e_child.icon,
          order: e_child.order,
          keepAlive: e_child.keepalive,
        },
      }))
    } else {
      // 没有子菜单，创建一个默认的子路由
      route.children.push({
        name: `${e.name}Default`,
        path: '',
        component: getComponent(e.component),
        isHidden: true,
        meta: {
          title: e.name,
          icon: e.icon,
          order: e.order,
          keepAlive: e.keepalive,
        },
      })
    }

    return route
  })
}

export const usePermissionStore = defineStore('permission', {
  state() {
    return {
      accessRoutes: [],
      accessApis: [],
    }
  },
  getters: {
    routes() {
      return basicRoutes.concat(this.accessRoutes)
    },
    menus() {
      return this.routes.filter((route) => route.name && !route.isHidden)
    },
    apis() {
      return this.accessApis
    },
  },
  actions: {
    async generateRoutes() {
      const res = await api.getUserMenu() // 调用接口获取后端传来的菜单路由
      this.accessRoutes = buildRoutes(res.data) // 处理成前端路由格式
      return this.accessRoutes
    },
    async getAccessApis() {
      const res = await api.getUserApi()
      // 后端返回 [{id, path, method, ...}] → 前端转为权限字符串 "method/path"
      const data = res.data || []
      this.accessApis = data.map((item) => {
        if (typeof item === 'string') return item
        const method = (item.method || '').toLowerCase()
        const path = item.path || ''
        return method + path
      })
      return this.accessApis
    },
    resetPermission() {
      this.$reset()
    },
  },
})
