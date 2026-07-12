export default {
  name: 'ConfigManager',
  path: '/config',
  meta: { title: '配置管理', icon: 'carbon:settings', order: 40 },
  redirect: '/config/manage',
  children: [
    {
      name: 'ConfigPanel',
      path: 'manage',
      component: '/config/manage',
      meta: { title: '配置中心', icon: 'carbon:settings-adjust' },
    },
    {
      name: 'ProviderBindings',
      path: 'bindings',
      component: '/config/bindings',
      meta: { title: '资源绑定', icon: 'carbon:ibm-cloud-pak-manta-automated-data-lineage' },
    },
  ],
}
