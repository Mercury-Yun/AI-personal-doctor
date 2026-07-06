import axios from 'axios'

const request = axios.create({
  baseURL: '/api',
  timeout: 25000,
})

request.interceptors.response.use(
  (response) => response,
  (error) => {
    if (!error.response) {
      if (error.code === 'ECONNABORTED') {
        error.message = '请求超时，语音或拍照可能仍在进行，请稍等后重试'
      } else {
        error.message = '无法连接服务器，请确认后端服务已启动'
      }
    } else if (typeof error.response.data?.detail === 'string' && error.response.data.detail.trim()) {
      error.message = error.response.data.detail
    }
    return Promise.reject(error)
  }
)

export default request
