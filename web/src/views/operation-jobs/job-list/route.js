export default {
  name: 'OperationJobs',
  path: '/operation-jobs',
  meta: { title: '任务中心', icon: 'carbon:task', order: 50 },
  children: [
    {
      name: 'JobList',
      path: 'job-list',
      component: '/operation-jobs/job-list',
      meta: { title: '任务列表', icon: 'carbon:task-view' },
    },
    {
      name: 'HubJobs',
      path: 'hub-jobs',
      component: '/operation-jobs/hub-jobs',
      meta: { title: 'Hub任务', icon: 'carbon:cloud-service-management' },
    },
  ],
}
