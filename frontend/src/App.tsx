import { useEffect, useRef, useState } from 'react'
import { ArrowDownToLine, ArrowRight, AudioLines, Check, ChevronDown, Clapperboard, Clock3, FileText, Layers3, LoaderCircle, LockKeyhole, Play, ScanLine, Search, Sparkles, Video, WandSparkles, Workflow, X } from 'lucide-react'
import { LiquidNavbar } from './components/ui/liquid-glass-navbar'

type Job = {
  id: string; topic: string; status: 'queued' | 'running' | 'succeeded' | 'failed'
  stage: string; progress: number; error: string | null; created_at: string
  artifacts: Record<string, string>
}
type Scene = { scene_id: string; title: string; narration: string; visual_concept: string }
const stages = [
  { keys: ['identify'], label: '理解主题', detail: '识别学科，明确讲解方向', icon: ScanLine },
  { keys: ['research'], label: '研究知识', detail: '检索资料，梳理核心概念', icon: Search },
  { keys: ['teaching'], label: '编写讲稿', detail: '组织讲解逻辑与旁白', icon: FileText },
  { keys: ['visual', 'assets', 'storyboard'], label: '设计分镜', detail: '安排画面，匹配动画素材', icon: Layers3 },
  { keys: ['generation'], label: '生成场景', detail: '将分镜转化为动画场景', icon: Clapperboard },
  { keys: ['rendering'], label: '合成视频', detail: '生成配音、渲染画面并合成', icon: Video },
]
const stageNames: Record<string, string> = { queued: '任务已排队', resuming: '正在恢复任务', identify: '正在理解主题', research: '正在研究知识', teaching: '正在编写讲稿', visual: '正在规划画面', assets: '正在匹配素材', storyboard: '正在设计分镜', generation: '正在生成场景', rendering: '正在合成视频', complete: '视频已生成' }
const stored = (key: string) => { try { return localStorage.getItem(key) || '' } catch { return '' } }
const save = (key: string, value: string) => { try { value ? localStorage.setItem(key, value) : localStorage.removeItem(key) } catch { /* Storage may be unavailable in private mode. */ } }
const initialId = new URLSearchParams(location.search).get('job') || stored('vibe.job')
const formatTime = (seconds: number) => `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`

class ApiError extends Error { constructor(message: string, public status: number) { super(message) } }
async function api(path: string, token: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body) headers.set('Content-Type', 'application/json')
  const response = await fetch(path, { ...init, headers, signal: init.signal ?? AbortSignal.timeout(20000) })
  if (!response.ok) {
    const messages: Record<number, string> = { 401: '请输入有效的访问令牌以连接服务。', 404: '没有找到这个任务，请重新创建视频。', 409: '任务状态已更新，请稍后重试。', 422: '请检查输入内容，知识点不能超过 300 字。', 429: '当前任务较多，请稍后再试。' }
    throw new ApiError(messages[response.status] || '服务暂时不可用，请稍后重试。', response.status)
  }
  return response
}

export default function App() {
  const [prompt, setPrompt] = useState(() => stored('vibe.draft'))
  const [active, setActive] = useState(0)
  const [jobId, setJobId] = useState(initialId)
  const [job, setJob] = useState<Job | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [loadingJob, setLoadingJob] = useState(!!initialId)
  const [connection, setConnection] = useState<'connecting' | 'online' | 'offline'>('connecting')
  const [error, setError] = useState('')
  const [pollError, setPollError] = useState('')
  const [requiresAuth, setRequiresAuth] = useState(false)
  const [token, setToken] = useState('')
  const [tokenInput, setTokenInput] = useState('')
  const [authOpen, setAuthOpen] = useState(false)
  const [scenes, setScenes] = useState<Scene[]>([])
  const [scriptOpen, setScriptOpen] = useState(false)
  const [scriptError, setScriptError] = useState('')
  const [videoSrc, setVideoSrc] = useState('')
  const [videoError, setVideoError] = useState('')
  const [mediaAttempt, setMediaAttempt] = useState(0)
  const [duration, setDuration] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const promptRef = useRef<HTMLTextAreaElement>(null)
  const actionPending = useRef(false)
  const working = job?.status === 'running' || job?.status === 'queued'
  const done = job?.status === 'succeeded'
  const failed = job?.status === 'failed'
  const currentStage = stages.findIndex(stage => stage.keys.includes(job?.stage || ''))
  const progress = Math.round((job?.progress || 0) * 100)
  const needsToken = requiresAuth && !token
  const planFile = job?.artifacts['storyboard.json'] ? 'storyboard.json' : job?.artifacts['teaching_plan.json'] ? 'teaching_plan.json' : ''

  useEffect(() => { save('vibe.draft', prompt) }, [prompt])
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const check = async () => {
      try {
        const response = await fetch('/ui-config', { signal: controller.signal })
        if (!response.ok) throw new Error('unavailable')
        const config = await response.json()
        if (controller.signal.aborted) return
        setRequiresAuth(config.requires_auth)
        setConnection('online')
      } catch { if (!controller.signal.aborted) setConnection('offline') }
      if (!controller.signal.aborted) timer = setTimeout(check, 15000)
    }
    void check()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [])

  useEffect(() => {
    if (!jobId || needsToken) { setLoadingJob(false); return }
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    let misses = 0
    const poll = async () => {
      try {
        const response = await api(`/jobs/${encodeURIComponent(jobId)}`, token, { signal: controller.signal })
        const next: Job = await response.json()
        if (controller.signal.aborted) return
        setJob(next); setPollError(''); setLoadingJob(false); setConnection('online'); misses = 0
        if (next.status === 'succeeded' || next.status === 'failed') return
      } catch (reason) {
        if (controller.signal.aborted) return
        misses++
        if (reason instanceof ApiError && reason.status === 401) { setRequiresAuth(true); setToken(''); setAuthOpen(true); setLoadingJob(false); return }
        if (reason instanceof ApiError && reason.status === 404) { setError(reason.message); rememberJob(''); setLoadingJob(false); return }
        setPollError('连接暂时中断，正在重新连接。任务仍会在后台继续。')
        setConnection('offline')
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, Math.min(10000, 2000 + misses * 1500))
    }
    void poll()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [jobId, token, needsToken, mediaAttempt])

  useEffect(() => {
    if (!job?.created_at) return
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - Date.parse(job.created_at)) / 1000)))
    tick()
    if (!working) return
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [job?.created_at, working])

  useEffect(() => {
    setScenes([]); setScriptError('')
    if (!jobId || !planFile || needsToken) return
    const controller = new AbortController()
    void api(`/jobs/${encodeURIComponent(jobId)}/artifacts/${planFile}`, token, { signal: controller.signal })
      .then(response => response.json()).then(plan => { if (!controller.signal.aborted) setScenes(plan.scenes || []) })
      .catch(() => { if (!controller.signal.aborted) setScriptError('讲稿暂时无法加载，请刷新页面重试。') })
    return () => controller.abort()
  }, [jobId, planFile, token, needsToken])

  useEffect(() => {
    setVideoSrc(''); setVideoError(''); setDuration(0)
    if (!done || !jobId || needsToken) return
    const url = `/jobs/${encodeURIComponent(jobId)}/video`
    if (!token) { setVideoSrc(url); return }
    // Authenticated media stays in memory; never put a token in a URL or storage.
    const controller = new AbortController()
    let blobUrl = ''
    void api(url, token, { signal: controller.signal }).then(response => response.blob()).then(blob => {
      if (controller.signal.aborted) return
      blobUrl = URL.createObjectURL(blob); setVideoSrc(blobUrl)
    }).catch(() => { if (!controller.signal.aborted) setVideoError('视频加载失败，请重试。') })
    return () => { controller.abort(); if (blobUrl) URL.revokeObjectURL(blobUrl) }
  }, [done, jobId, token, needsToken, mediaAttempt])

  function rememberJob(id: string) {
    setJobId(id); save('vibe.job', id)
    const url = new URL(location.href)
    id ? url.searchParams.set('job', id) : url.searchParams.delete('job')
    history.replaceState(null, '', url)
  }

  function navigate(index: number) {
    setActive(index)
    document.getElementById(['create', 'process', 'result'][index])?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'center' })
    if (index === 0) promptRef.current?.focus({ preventScroll: true })
  }

  async function generate(resume = false) {
    if (actionPending.current || (!resume && (!prompt.trim() || working || loadingJob))) return
    if (needsToken) { setAuthOpen(true); return }
    actionPending.current = true; setSubmitting(true); setError('')
    try {
      const response = await api(resume ? `/jobs/${encodeURIComponent(jobId)}/resume` : '/jobs', token, {
        method: 'POST', ...(!resume && { body: JSON.stringify({ topic: prompt.trim(), mode: 'live', renderer: 'auto', tts_enabled: true, playback_speed: 1.15 }) }),
      })
      const next: Job = await response.json()
      setJob(next); rememberJob(next.id); setScenes([]); setScriptOpen(false); setActive(1); setPollError('')
      // Resume reuses the ID, so explicitly restart the polling effect.
      setMediaAttempt(value => value + 1)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '提交失败，请重试。')
      if (reason instanceof ApiError && reason.status === 401) { setRequiresAuth(true); setToken(''); setAuthOpen(true) }
    } finally { actionPending.current = false; setSubmitting(false) }
  }

  const statusText = loadingJob ? '正在恢复任务' : failed ? '任务需要重试' : done ? '全部完成' : job ? stageNames[job.stage] || '正在处理' : '等待开始'

  return <div className="app-shell">
    <a className="skip-link" href="#create">跳到知识点输入</a>
    <header className="topbar">
      <a className="brand" href="#create" onClick={() => navigate(0)} aria-label="Vibe 知识视频工作台">
        <span className="brand-symbol"><span /></span><span className="brand-name">vibe<span className="brand-dot">.</span></span><span className="brand-caption">知识视频工作台</span>
      </a>
      <LiquidNavbar compact={false} active={active} onChange={navigate} sound={false} items={[
        { label: '开始创作', icon: <WandSparkles size={17} />, fx: 'pop' },
        { label: 'Agent 过程', icon: <Workflow size={17} />, fx: 'spin' },
        { label: '视频成果', icon: <Play size={17} />, fx: 'pop' },
      ]} />
      <div className="service-status" role="status"><span className={`status-dot ${connection}`} />{connection === 'online' ? '服务已连接' : connection === 'offline' ? '等待连接' : '正在连接'}{requiresAuth && <button className="icon-button" onClick={() => setAuthOpen(true)} aria-label="设置访问令牌"><LockKeyhole size={15} /></button>}</div>
    </header>

    <main>
      <section className="intro" aria-labelledby="page-title">
        <div className="eyebrow"><span /> FROM CURIOSITY TO CLARITY</div>
        <h1 id="page-title">一个知识点，<span>一支好视频。</span></h1>
        <p>写下你想理解的内容，剩下的交给 Agent。</p>
      </section>

      <div className="workspace">
        <div className="creation-column">
          <section className="glass-panel composer" id="create" aria-labelledby="create-title">
            <div className="section-heading"><h2 id="create-title"><span className="section-number">01</span>你想讲解什么？</h2><Sparkles className="heading-accent" size={19} /></div>
            <form onSubmit={event => { event.preventDefault(); void generate() }}>
              <label className="sr-only" htmlFor="topic">输入要讲解的知识点</label>
              <div className="prompt-wrap">
                <textarea ref={promptRef} id="topic" value={prompt} maxLength={300} placeholder={'输入你想讲解的知识点…\n比如：为什么导数能描述瞬时变化率？'} onChange={event => setPrompt(event.target.value)} onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && !event.nativeEvent.isComposing) { event.preventDefault(); void generate() } }} aria-describedby="prompt-hint" />
                <span className="char-count">{prompt.length}<span> / 300</span></span>
              </div>
              <div className="composer-actions"><span id="prompt-hint">一个概念，也可以是一个问题</span><button className="primary-button" type="submit" disabled={!prompt.trim() || submitting || working || loadingJob || connection !== 'online'}>{submitting || working ? <LoaderCircle size={16} className="spin" /> : <Sparkles size={16} />}{submitting ? '正在提交' : working ? '正在生成' : '生成视频'}{!submitting && !working && <ArrowRight size={16} />}</button></div>
            </form>
            {error && <div className="notice error-notice" role="alert"><span>{error}</span><button className="icon-button" aria-label="关闭提示" onClick={() => setError('')}><X size={15} /></button></div>}
            {needsToken && <button className="text-button auth-trigger" onClick={() => setAuthOpen(true)}><LockKeyhole size={14} />连接服务需要访问令牌</button>}
          </section>

          <section className="glass-panel process-panel" id="process" aria-labelledby="process-title">
            <div className="section-heading"><h2 id="process-title"><span className="section-number">02</span>Agent 处理过程</h2><span className={`state-tag ${working ? 'working' : ''} ${done ? 'done' : ''} ${failed ? 'failed' : ''}`}>{working && <span className="status-dot online" />}{done && <Check size={12} />}{failed ? '已暂停' : done ? '已完成' : working ? '进行中' : '待开始'}</span></div>
            <div className="progress-label"><span aria-live="polite">{statusText}</span><span className="progress-number">{progress}<small>%</small></span></div>
            <div className="progress-track" role="progressbar" aria-label="Agent 处理进度" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${progress}%` }} /></div>
            <ol className="stage-list">
              {stages.map((stage, index) => {
                const complete = done || index < currentStage
                const current = !done && index === currentStage
                const Icon = stage.icon
                return <li key={stage.label} className={`stage ${complete ? 'complete' : ''} ${current ? 'current' : ''} ${current && failed ? 'stage-failed' : ''}`} aria-current={current ? 'step' : undefined}>
                  <span className="stage-icon">{complete ? <Check size={16} /> : <Icon size={16} />}</span>
                  <div className="stage-copy"><span className="stage-name">{stage.label}</span><span className="stage-detail">{stage.detail}</span></div>
                  <span className="stage-state">{complete ? '完成' : current && failed ? '中断' : current ? <LoaderCircle size={15} className="spin" aria-label="处理中" /> : <span className="waiting-dash">—</span>}</span>
                </li>
              })}
            </ol>
            {(working || done || failed) && <div className="process-foot">{working ? <span><Clock3 size={13} />已用时 {formatTime(elapsed)}</span> : <span><Workflow size={13} />{done ? '全部阶段已完成' : '已保留完成的步骤'}</span>}<span>{working ? '可离开页面，稍后回来' : done ? '成片已就绪' : '可从中断处继续'}</span></div>}
            {pollError && <p className="notice" role="status">{pollError}</p>}
            {failed && <div className="failure-box" role="alert"><p>生成暂时中断</p><details><summary>查看原因</summary><pre>{job.error || '任务执行失败，请重试。'}</pre></details><button className="secondary-button" disabled={submitting} onClick={() => void generate(true)}>{submitting ? '正在恢复…' : '继续此任务'}<ArrowRight size={14} /></button></div>}
          </section>
        </div>

        <section className="glass-panel result-panel" id="result" aria-labelledby="result-title">
          <div className="section-heading"><h2 id="result-title"><span className="section-number">03</span>视频成果</h2><span className="format-badge">16 : 9</span></div>
          <div className={`video-stage ${done ? 'ready' : ''} ${working ? 'producing' : ''}`}>
            {done && videoSrc && !videoError ? <video key={`${videoSrc}-${mediaAttempt}`} src={videoSrc} controls playsInline preload="metadata" aria-label={job.topic + '，知识讲解视频'} onLoadedMetadata={event => setDuration(event.currentTarget.duration)} onError={() => setVideoError('视频暂时无法播放，请重新加载。')} /> : <div className="video-empty">
              <div className="video-orbit" aria-hidden="true"><span className="orbit-ring ring-one" /><span className="orbit-ring ring-two" /><div className="glass-play">{working ? <AudioLines size={36} strokeWidth={1.3} /> : <Play size={34} strokeWidth={1.3} />}</div><span className="orbit-spark spark-one" /><span className="orbit-spark spark-two" /></div>
              <h3>{videoError ? '视频加载遇到问题' : done ? '正在加载视频' : failed ? '等待任务继续' : working ? '知识正在成为画面' : '让想法，在这里成片'}</h3>
              <p>{videoError || (done ? '成片已生成，即将可以播放' : failed ? '继续左侧任务，完成后即可观看' : working ? 'Agent 正在制作，完成后将在这里呈现' : '输入知识点，开始你的第一支讲解视频')}</p>
              {videoError && <button className="secondary-button" onClick={() => setMediaAttempt(value => value + 1)}>重新加载</button>}
            </div>}
            {!done && <span className="preview-caption"><span />{working ? '制作中' : '视频预览'}</span>}
          </div>
          <div className="video-info"><div><p className="video-title">{job?.topic || '从一个好问题开始'}</p><p className="video-description">{done ? `${duration ? formatTime(duration) + ' · ' : ''}MP4 · 画面、字幕与配音已同步` : working ? `${stageNames[job.stage] || '正在处理'} · 完成后即可播放和下载` : failed ? '讲稿与中间产物已保留' : '讲稿、分镜、动画与配音，一次完成。'}</p></div>{done && videoSrc && <a className="download-button" href={videoSrc} download="vibe-video.mp4"><ArrowDownToLine size={16} />下载视频</a>}</div>
          <div className="result-divider" />
          {planFile ? <div className="script-section"><button className="script-toggle" onClick={() => setScriptOpen(value => !value)} aria-expanded={scriptOpen} aria-controls="script-content"><span><FileText size={16} />讲稿与分镜{scenes.length > 0 && <small>{scenes.length} 个场景</small>}</span><ChevronDown size={16} className={scriptOpen ? 'rotated' : ''} /></button>{scriptOpen && <div className="script-content" id="script-content">{scriptError ? <p role="status">{scriptError}</p> : scenes.length === 0 ? <p>正在加载讲稿…</p> : scenes.map((scene, index) => <article key={scene.scene_id}><h3><span>{String(index + 1).padStart(2, '0')}</span>{scene.title}</h3><p>{scene.narration}</p>{scene.visual_concept && <p className="scene-visual">画面 · {scene.visual_concept}</p>}</article>)}</div>}</div> : <div className="result-note"><span className="note-icon"><Clapperboard size={19} strokeWidth={1.4} /></span><div><h3>从文字到画面，每一步都看得见</h3><p>左侧实时展示处理进度，讲稿生成后可在这里展开查看。</p></div></div>}
          <div className="result-bottom"><span><AudioLines size={14} />有声讲解</span><span><FileText size={14} />同步字幕</span><span><Layers3 size={14} />知识动画</span></div>
        </section>
      </div>
      <footer><span>VIBE KNOWLEDGE STUDIO</span><span>少一点理解的距离。</span></footer>
    </main>
    {authOpen && <div className="modal-backdrop" onClick={event => { if (event.target === event.currentTarget) setAuthOpen(false) }}><dialog open aria-labelledby="auth-title" onKeyDown={event => { if (event.key === 'Escape') setAuthOpen(false) }}><div className="section-heading"><h2 id="auth-title">连接视频服务</h2><button className="icon-button" aria-label="关闭" onClick={() => setAuthOpen(false)}><X size={18} /></button></div><p>输入服务端配置的访问令牌，仅用于当前页面会话。</p><form onSubmit={event => { event.preventDefault(); setToken(tokenInput.trim()); setTokenInput(''); setAuthOpen(false); setError('') }}><label htmlFor="token">访问令牌</label><input autoFocus id="token" type="password" autoComplete="off" value={tokenInput} onChange={event => setTokenInput(event.target.value)} required /><button className="primary-button" type="submit">连接服务<ArrowRight size={16} /></button></form></dialog></div>}
  </div>
}
