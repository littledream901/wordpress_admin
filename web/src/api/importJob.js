import { request } from '@/utils'

export default {
  getList(params) { return request.get('/import/list', { params }) },
  upload(type, formData) {
    return request.post(`/import/${type}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  downloadTemplate(type) {
    return request.get('/import/template/' + type, { responseType: 'blob' })
      .then(blob => {
        const url = window.URL.createObjectURL(new Blob([blob]))
        const link = document.createElement('a')
        link.href = url
        link.download = type + '.csv'
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
        window.URL.revokeObjectURL(url)
      })
  },
}
