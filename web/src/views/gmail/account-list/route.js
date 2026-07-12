export default {
  name: 'GmailManager',
  path: '/gmail',
  meta: { title: 'Gmail管理', icon: 'mdi:gmail', order: 20 },
  children: [
    {
      path: 'account-list',
      name: 'GmailAccountList',
      component: '/gmail/account-list',
      meta: { title: 'Gmail账号', icon: 'mdi:account-box-mail' },
    },
  ],
}
