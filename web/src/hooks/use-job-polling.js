import {
  tryRefreshToken,
  forceLogout,
  registerStopAllPollingHandler,
  isForceLoggingOut,
} from '@/utils/auth-manager'

// ── 退避策略 ──
function nextBackoff(retries) {
  if (retries <= 0) return 5000
  if (retries === 1) return 10000
  if (retries === 2) return 20000
  return -1 // 停止
}

// ── 轮询仓库 ──
const jobs = new Map()
let timer = null

function ensureTimer() {
  if (timer) return
  timer = setInterval(tick, 1000)
}

function clearTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

async function tick() {
  if (isForceLoggingOut()) return

  const now = Date.now()
  const list = Array.from(jobs.values())

  for (const job of list) {
    if (job.stopped) continue
    if (job.nextRunAt && now < job.nextRunAt) continue
    await pollOne(job)
  }

  if (jobs.size === 0) {
    clearTimer()
  }
}

async function pollOne(job) {
  if (!job || !job.fetcher) return

  try {
    const res = await job.fetcher(job.jobId)
    const data = res && res.data ? res.data : null

    job.retries = 0
    job.nextRunAt = Date.now() + 5000

    if (!data) {
      stopJob(job.jobId)
      if (job.onStop) job.onStop('empty')
      return
    }

    if (job.onData) {
      job.onData(data)
    }

    // 终态 → 停止
    if (['success', 'failed', 'cancelled'].includes(data.status)) {
      stopJob(job.jobId)
      if (job.onFinish) job.onFinish(data)
    }
  } catch (err) {
    const status = err && err.response ? err.response.status : 0

    // 401 → 全局 refresh → 失败则 forceLogout
    if (status === 401) {
      const refreshed = await tryRefreshToken()
      if (!refreshed) {
        stopAllJobs()
        await forceLogout()
        return
      }
      job.nextRunAt = Date.now() + 1000
      return
    }

    // 403 / 404 / 422 → 停止该任务
    if (status === 403) {
      stopJob(job.jobId)
      if (job.onStop) job.onStop('forbidden', err)
      return
    }
    if (status === 404) {
      stopJob(job.jobId)
      if (job.onStop) job.onStop('not_found', err)
      return
    }
    if (status === 422) {
      stopJob(job.jobId)
      if (job.onStop) job.onStop('invalid', err)
      return
    }

    // 500 / 网络错误 → 退避重试
    job.retries += 1
    const delay = nextBackoff(job.retries)
    if (delay < 0) {
      stopJob(job.jobId)
      if (job.onStop) job.onStop('retry_exhausted', err)
      return
    }
    job.nextRunAt = Date.now() + delay
  }
}

// ── 公开 API ──

/**
 * 启动任务轮询
 * @param {Object} options
 * @param {number} options.jobId
 * @param {Function} options.fetcher - (jobId) => Promise，返回 job 数据
 * @param {Function} [options.onData] - 每次轮询成功后回调
 * @param {Function} [options.onFinish] - 任务终态回调
 * @param {Function} [options.onStop] - 停止轮询回调（可传入原因）
 */
export function startJobPolling(options) {
  const { jobId, fetcher, onData, onFinish, onStop } = options || {}
  if (!jobId || typeof fetcher !== 'function') return
  if (jobs.has(jobId)) return

  jobs.set(jobId, {
    jobId,
    fetcher,
    onData,
    onFinish,
    onStop,
    retries: 0,
    stopped: false,
    nextRunAt: Date.now(), // 立即执行第一次
  })

  ensureTimer()
}

/** 停止单个任务 */
export function stopJob(jobId) {
  jobs.delete(jobId)
  if (jobs.size === 0) {
    clearTimer()
  }
}

/** 停止全部任务（forceLogout 调用链路） */
export function stopAllJobs() {
  jobs.clear()
  clearTimer()
}

// 注册全局停止回调：forceLogout 时自动停止所有轮询
registerStopAllPollingHandler(stopAllJobs)
