import { request } from '@/utils'

export default {
  getOnepanelMonitor(params = {}) {
    return request.get('/site-pipeline/onepanel-monitor', { params })
  },
}
