export default {
  name: 'SitePipeline',
  path: '/site-pipeline',
  meta: { title: '站点流水线', icon: 'mdi:web', order: 10 },
  children: [
    {
      path: 'site-list',
      name: 'SitePipelineSiteList',
      component: '/site-pipeline/site-list',
      meta: { title: '站点管理', icon: 'mdi:server-network' },
    },
  ],
}
