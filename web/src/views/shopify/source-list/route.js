export default {
  name: 'ShopifyManager',
  path: '/shopify',
  meta: { title: 'Shopify采集', icon: 'mdi:shopping-search', order: 30 },
  children: [
    {
      path: 'source-list',
      name: 'ShopifySourceList',
      component: '/shopify/source-list',
      meta: { title: '待采集列表', icon: 'mdi:link-variant' },
    },
    {
      path: 'product-list',
      name: 'ShopifyProductList',
      component: '/shopify/product-list',
      meta: { title: '产品列表', icon: 'mdi:package-variant-closed' },
    },
  ],
}
