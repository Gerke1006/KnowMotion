import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCheck,
  ChevronRight,
  CircleAlert,
  Copy,
  History,
  Library,
  LoaderCircle,
  Menu,
  Plus,
  RotateCcw,
  Settings2,
  Square,
  Sparkles,
  TrendingUp,
  Triangle,
  Trash2,
  Landmark,
  Video,
  Workflow,
} from "lucide-react";
import { ApiSettings } from "./components/ApiSettings";
import { Sidebar } from "./components/Sidebar";
import { VideoThumbnail } from "./components/StudioMedia";
import { TaskProgress } from "./components/TaskProgress";
import { ProductionPreview } from "./components/ProductionPreview";
import { DeleteHistoryDialog } from "./components/DeleteHistoryDialog";
import { CancelJobDialog } from "./components/CancelJobDialog";
import { CreationComposer } from "./components/CreationComposer";
import derivativeCover from "./assets/showcase/derivative.svg";
import geometryCover from "./assets/showcase/geometry.svg";
import historyCover from "./assets/showcase/history.svg";
import {
  api,
  ApiError,
  getDraft,
  observeJob,
  readRoute,
  saveDraft,
  stageLabels,
  statusLabels,
  timeLabel,
  type Job,
  type GenerationState,
  type StudioRoute,
  type UiConfig,
} from "./studio";

const suggestions = [
  { title: "看见函数的变化", detail: "让割线靠近切线，把瞬时变化率讲清楚。", prompt: "用直观的动画解释，为什么导数表示瞬时变化率。", icon: TrendingUp, tone: "teal", category: "微积分", cover: derivativeCover },
  { title: "发现几何的直觉", detail: "从三个正方形出发，用面积理解勾股定理。", prompt: "用面积变化和几何图形，直观解释勾股定理。", icon: Triangle, tone: "blue", category: "几何", cover: geometryCover },
  { title: "走进历史的现场", detail: "沿着丝绸之路，读懂张骞的远行。", prompt: "讲解张骞出使西域的背景、经过与影响。", icon: Landmark, tone: "sand", category: "历史", cover: historyCover },
];

export default function Workspace({ token, onTokenChange, onHome }: {
  token: string;
  onTokenChange: (token: string) => void;
  onHome: () => void;
}) {
  const [route, setRoute] = useState<StudioRoute>(readRoute);
  const [prompt, setPrompt] = useState(getDraft);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [jobsError, setJobsError] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [jobError, setJobError] = useState("");
  const [connected, setConnected] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [submitMode, setSubmitMode] = useState<"new" | "resume">("new");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [copied, setCopied] = useState(false);
  const [toast, setToast] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Job | null>(null);
  const [cancelTarget, setCancelTarget] = useState<Job | null>(null);
  const [cancelSubmittingId, setCancelSubmittingId] = useState<string | null>(null);
  const cancellingRequest = useRef(false);
  const [uiConfig, setUiConfig] = useState<UiConfig | null>(null);
  const [configError, setConfigError] = useState(false);
  const [generationState, setGenerationState] = useState<GenerationState | null>(null);
  const [stateConnected, setStateConnected] = useState(false);
  const lastActiveId = useRef<string | null>(null);
  const promptRef = useRef(prompt);
  promptRef.current = prompt;
  const deletedIds = useRef(new Set<string>());
  const routeRef = useRef(route);
  routeRef.current = route;
  const pending = useRef(false);
  const mounted = useRef(true);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const workspace = useRef<HTMLDivElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const completed = jobs.filter((item) => item.status === "succeeded");
  const current = job?.id === route.id ? job : null;
  const publicMode = Boolean(uiConfig?.public_mode);
  const sharedGeneration = Boolean(uiConfig?.single_generation);
  const sharedJob = generationState?.active_job;
  const stopping = Boolean(cancelSubmittingId) || sharedJob?.status === "cancelling" || current?.status === "cancelling";
  const generationBlocked = !uiConfig || stopping || (sharedGeneration && (!stateConnected || Boolean(generationState?.busy)));
  const blockedLabel = !uiConfig ? "正在连接服务" : stopping ? "等待制作停止" : !stateConnected ? "正在同步状态" : "等待当前制作完成";

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const response = await api("/ui-config", token, { signal: controller.signal });
        const data: UiConfig = await response.json();
        if (controller.signal.aborted) return;
        setUiConfig(data);
        setConfigError(false);
      } catch {
        if (controller.signal.aborted) return;
        setConfigError(true);
        timer = setTimeout(load, 5000);
      }
    };
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [token]);

  useEffect(() => {
    if (!sharedGeneration) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let firstSnapshot = true;
    const poll = async () => {
      try {
        const response = await api("/generation-state", token, { signal: controller.signal });
        const data: GenerationState = await response.json();
        if (controller.signal.aborted) return;
        const active = data.active_job ? observeJob(data.active_job) : null;
        setGenerationState({ ...data, active_job: active });
        setStateConnected(true);
        if (lastActiveId.current !== (active?.id || null)) {
          lastActiveId.current = active?.id || null;
          setRefresh((value) => value + 1);
        }
        if (active) {
          setJobs((previous) => [active, ...previous.filter((item) => item.id !== active.id)]);
          // A visitor arriving in the empty composer joins the current shared
          // production; someone drafting a topic keeps their input and view.
          if (firstSnapshot && routeRef.current.view === "new" && !promptRef.current.trim()) openJob(active);
        }
        firstSnapshot = false;
      } catch {
        if (controller.signal.aborted) return;
        setStateConnected(false);
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 2500);
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [sharedGeneration, token]);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    saveDraft(prompt);
  }, [prompt]);
  useEffect(() => {
    const pop = () => {
      setRoute(readRoute());
      setSidebarOpen(false);
    };
    window.addEventListener("popstate", pop);
    return () => {
      window.removeEventListener("popstate", pop);
      clearTimeout(copyTimer.current);
    };
  }, []);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    if (!sidebarOpen || !matchMedia("(max-width: 760px)").matches) return;
    const previous = document.activeElement as HTMLElement;
    sidebarRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSidebarOpen(false);
      if (event.key !== "Tab") return;
      const items = Array.from(
        sidebarRef.current?.querySelectorAll<HTMLButtonElement>(
          "button:not(:disabled)",
        ) || [],
      );
      const first = items[0],
        last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      previous?.focus();
    };
  }, [sidebarOpen]);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const response = await api("/jobs?limit=200", token, {
          signal: controller.signal,
        });
        const data: Job[] = await response.json();
        if (controller.signal.aborted) return;
        setJobs(data.map(observeJob).filter((item) => item.mode === "live" && !deletedIds.current.has(item.id)));
        setJobsError("");
        setConnected(true);
      } catch (error) {
        if (controller.signal.aborted) return;
        setJobsError(error instanceof Error ? error.message : "记录加载失败");
        setConnected(false);
      } finally {
        if (!controller.signal.aborted) setJobsLoading(false);
      }
      if (!controller.signal.aborted) timer = setTimeout(load, 7000);
    };
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [token, refresh]);

  useEffect(() => {
    setJobError("");
    setCopied(false);
    if (!route.id) return;
    setJob((previous) => (previous?.id === route.id ? previous : null));
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const response = await api(
          `/jobs/${encodeURIComponent(route.id!)}`,
          token,
          { signal: controller.signal },
        );
        const data = observeJob((await response.json()) as Job);
        if (controller.signal.aborted || deletedIds.current.has(data.id)) return;
        setJob(data);
        setJobError("");
        setConnected(true);
        setJobs((previous) =>
          [data, ...previous.filter((item) => item.id !== data.id)].sort(
            (a, b) => b.created_at.localeCompare(a.created_at),
          ),
        );
        if (data.status === "succeeded" || data.status === "failed" || data.status === "cancelled") return;
      } catch (error) {
        if (controller.signal.aborted) return;
        setJobError(error instanceof Error ? error.message : "无法读取任务");
        if (error instanceof ApiError && [401, 404].includes(error.status))
          return;
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 2500);
    };
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [route.id, token, refresh]);

  function navigate(next: StudioRoute) {
    const url = new URL(location.href);
    url.pathname = "/workspace";
    url.search = "";
    url.hash = "";
    if (next.id) url.searchParams.set("job", next.id);
    else if (next.view !== "new") url.searchParams.set("view", next.view);
    history.pushState(null, "", url);
    setRoute(next);
    setSidebarOpen(false);
    setSubmitError("");
    workspace.current?.scrollTo({ top: 0, behavior: "instant" });
  }
  function openJob(item: Job) {
    setJob(item);
    navigate({ view: "history", id: item.id });
  }
  function newVideo() {
    navigate({ view: "new" });
  }
  async function stopJob(item: Job) {
    if (!uiConfig?.can_cancel_jobs || cancellingRequest.current) return;
    cancellingRequest.current = true;
    setCancelSubmittingId(item.id);
    try {
      let updated: Job;
      try {
        const response = await api(`/jobs/${encodeURIComponent(item.id)}/cancel`, token, { method: "POST" });
        updated = observeJob(await response.json() as Job);
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 409)) throw error;
        // Completion may win the race with stop, or another visitor may stop it.
        const response = await api(`/jobs/${encodeURIComponent(item.id)}`, token);
        updated = observeJob(await response.json() as Job);
        if (updated.status === "queued" || updated.status === "running") {
          throw new Error("任务状态已更新，停止请求尚未确认，请重试。");
        }
      }
      if (!mounted.current) return;
      setJob((previous) => previous?.id === updated.id ? updated : previous);
      setJobs((previous) => previous.map((record) => record.id === updated.id ? updated : record));
      if (sharedGeneration) {
        // Only a fresh shared-state response may free the generation button.
        // A cancelling response still represents running background processes.
        setStateConnected(false);
        try {
          const stateResponse = await api("/generation-state", token);
          const state: GenerationState = await stateResponse.json();
          if (!mounted.current) return;
          setGenerationState({ ...state, active_job: state.active_job ? observeJob(state.active_job) : null });
          setStateConnected(true);
        } catch {
          // Regular polling retries; submission stays disabled while disconnected.
        }
      }
      if (!mounted.current) return;
      setCancelTarget(null);
      setRefresh((value) => value + 1);
      setToast(updated.status === "cancelled" ? "制作已停止，草稿已保留。"
        : updated.status === "cancelling" ? "正在停止制作，完成后即可开始新视频。"
        : "任务已经结束，状态已更新。");
    } finally {
      cancellingRequest.current = false;
      if (mounted.current) setCancelSubmittingId(null);
    }
  }
  async function deleteHistory(item: Job) {
    if (!uiConfig?.can_delete_jobs) return;
    try {
      await api(`/jobs/${encodeURIComponent(item.id)}`, token, { method: "DELETE" });
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 404)) {
        if (error instanceof ApiError && error.status === 409) {
          throw new Error("任务仍在制作中，请等它结束后再删除。");
        }
        throw error;
      }
      // A record removed in another tab is already in the requested state.
    }
    if (!mounted.current) return;
    deletedIds.current.add(item.id);
    setJobs((previous) => previous.filter((record) => record.id !== item.id));
    setJob((previous) => previous?.id === item.id ? null : previous);
    setDeleteTarget(null);
    setSidebarOpen(false);
    if (routeRef.current.id === item.id) navigate({ view: "history" });
    setRefresh((value) => value + 1);
    setToast("记录已删除");
  }
  async function generate(resume = false) {
    if (pending.current || generationBlocked || (!resume && !prompt.trim()) || (resume && !current))
      return;
    pending.current = true;
    setSubmitMode(resume ? "resume" : "new");
    setSubmitting(true);
    setSubmitError("");
    try {
      const response = await api(
        resume ? `/jobs/${encodeURIComponent(current!.id)}/resume` : "/jobs",
        token,
        {
          method: "POST",
          ...(!resume && {
            body: JSON.stringify({
              topic: prompt.trim(),
              mode: "live",
              renderer: "auto",
              tts_enabled: true,
              playback_speed: 1.15,
            }),
          }),
        },
      );
      const created = observeJob((await response.json()) as Job);
      if (!mounted.current) return;
      if (sharedGeneration) setGenerationState({ busy: true, active_job: created });
      setJob(created);
      setJobs((previous) => [
        created,
        ...previous.filter((item) => item.id !== created.id),
      ]);
      navigate({ view: "history", id: created.id });
      setRefresh((value) => value + 1);
      if (!resume) {
        setPrompt("");
        saveDraft("");
      }
    } catch (error) {
      if (!mounted.current) return;
      setSubmitError(
        error instanceof Error ? error.message : "提交失败，请重试。",
      );
      if (!publicMode && error instanceof ApiError && error.status === 401)
        setSettingsOpen(true);
      if (error instanceof ApiError && error.status === 409)
        setRefresh((value) => value + 1);
    } finally {
      pending.current = false;
      if (mounted.current) setSubmitting(false);
    }
  }
  async function copyPrompt() {
    if (!current) return;
    try {
      await navigator.clipboard.writeText(current.topic);
      setCopied(true);
      clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(false), 1800);
    } catch {
      setToast("复制失败，请选中文字复制。");
    }
  }
  const contentError = (message: string, retry?: () => void) => (
    <div className="inline-message" role="alert">
      <CircleAlert size={16} />
      <span>{message}</span>
      <button
        type="button"
        className="button-quiet"
        onClick={() => {
          if (!publicMode && message.includes("令牌")) setSettingsOpen(true);
          else if (retry) retry();
          else setRefresh((value) => value + 1);
        }}
      >
        重试
      </button>
    </div>
  );
  const stopButton = (item: Job) => uiConfig?.can_cancel_jobs && ["queued", "running", "cancelling"].includes(item.status) && (
    <button type="button" className="button-quiet stop-production-button"
      disabled={Boolean(cancelSubmittingId) || item.status === "cancelling" || (sharedGeneration && !stateConnected)}
      onClick={() => setCancelTarget(item)}>
      {item.status === "cancelling" || cancelSubmittingId === item.id ? <LoaderCircle size={14} className="spin" /> : <Square size={14} />}
      {item.status === "cancelling" || cancelSubmittingId === item.id ? "正在停止" : "停止制作"}
    </button>
  );

  return (
    <div className={`studio-shell canvas-studio ${sidebarOpen ? "mobile-menu-open" : ""}`}>
      <a href="#main-content" className="skip-link">
        跳到主内容
      </a>
      {sidebarOpen && (
        <button
          className="sidebar-scrim"
          aria-label="关闭导航"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <Sidebar sidebarRef={sidebarRef} route={route} jobs={jobs}
        jobsLoading={jobsLoading} jobsError={jobsError} connected={connected}
        onHome={onHome} onNew={newVideo} onNavigate={navigate} onOpenJob={openJob}
        onDeleteJob={uiConfig?.can_delete_jobs ? setDeleteTarget : undefined}
        onClose={() => setSidebarOpen(false)} />
      <div className="studio-main">
        <header className="workspace-header">
          <div className="header-path">
            <button
              className="icon-button menu-toggle"
              onClick={() => setSidebarOpen(true)}
              aria-label="打开导航"
              aria-expanded={sidebarOpen}
            >
              <Menu size={20} />
            </button>
            <span className="header-section-icon">
              {route.view === "new" ? (
                <Sparkles size={17} />
              ) : route.view === "library" ? (
                <Library size={17} />
              ) : (
                <History size={17} />
              )}
            </span>
            <span>
              {route.view === "new"
                ? "新建视频"
                : route.view === "library"
                  ? "视频库"
                  : "历史记录"}
            </span>
            {route.id && (
              <>
                <ChevronRight size={14} className="breadcrumb-chevron" />
                <span className="breadcrumb-topic">
                  {current?.topic || "视频详情"}
                </span>
              </>
            )}
          </div>
          <div className="header-actions">
            <span className="header-status" role="status">
              <i className={connected ? "online" : ""} />
              {connected ? "制作服务已连接" : jobsLoading ? "正在连接" : "服务未连接"}
            </span>
            {uiConfig?.can_edit_settings && <button
              className="api-settings-button"
              onClick={() => setSettingsOpen(true)}
            >
              <Settings2 size={16} />
              <span>自定义接口</span>
            </button>}
          </div>
        </header>
        {publicMode && (
          <div className={`shared-production-banner ${generationState?.busy ? "is-busy" : ""}`} role="status">
            {generationState?.busy ? <LoaderCircle size={17} className="spin" /> : <Workflow size={17} />}
            <div>
              <strong>{generationState?.busy ? `${sharedJob?.status === "cancelling" ? "正在停止" : "大家正在制作"}：${sharedJob?.topic || "知识视频"}` : "公共创作空间"}</strong>
              <span>{!stateConnected ? "正在重新连接，状态同步后即可继续操作。" : sharedJob
                ? sharedJob.status === "cancelling" ? "正在结束当前制作，请稍等；完全停止后即可制作下一个视频。"
                  : `${stageLabels[sharedJob.stage] || "正在制作"} · ${Math.round(sharedJob.progress * 100)}% · 可等待完成或停止本次制作`
                : "所有人共享视频与制作过程，同一时间制作一个视频。"}</span>
            </div>
            {sharedJob && <div className="shared-production-actions">
              {route.id !== sharedJob.id && <button className="button-quiet" onClick={() => openJob(sharedJob)}>查看进度<ArrowRight size={14} /></button>}
              {stopButton(sharedJob)}
            </div>}
          </div>
        )}
        {configError && <div className="shared-production-banner" role="status"><CircleAlert size={17} /><span>暂时无法连接制作服务，正在重试…</span></div>}
        <div
          ref={workspace}
          className="workspace-scroll"
          id="main-content"
          tabIndex={-1}
        >
          {route.view === "new" && (
            <main className="create-page creator-page page-enter">
              <div className="creator-welcome">
                <div className="create-heading">
                  <h1>你好，想让什么知识动起来？</h1>
                </div>
                <section className="topic-suggestions" aria-label="创作灵感">
                  <div className="suggestion-grid">
                    {suggestions.map((suggestion) => (
                      <button key={suggestion.title} className="topic-suggestion" data-tone={suggestion.tone}
                        disabled={submitting}
                        onClick={() => { setPrompt(suggestion.prompt); textarea.current?.focus(); }}>
                        <span className="suggestion-art">
                          <img src={suggestion.cover} alt="" />
                          <span className="suggestion-art-label"><suggestion.icon size={14} /><span>{suggestion.category}</span></span>
                        </span>
                        <span className="suggestion-card-body">
                          <strong>{suggestion.title}</strong>
                          <small>{suggestion.detail}</small>
                          <span className="suggestion-try">试一试<ArrowRight size={14} /></span>
                        </span>
                      </button>
                    ))}
                  </div>
                </section>
              </div>
            </main>
          )}
          {route.view === "library" && (
            <main className="collection-page page-enter">
              <div className="page-heading">
                <div>
                  <h1>
                    视频库
                    <span className="count-badge">{completed.length}</span>
                  </h1>
                  <p>每一次理解，都值得留下。</p>
                </div>
                <button className="button-primary" onClick={newVideo}>
                  <Plus size={17} />
                  新建视频
                </button>
              </div>
              <div className="collection-tabs">
                <span>
                  <Video size={17} />
                  全部视频
                </span>
              </div>
              {jobsError && contentError(jobsError)}
              {jobsLoading ? (
                <div className="collection-loading">
                  <LoaderCircle size={22} className="spin" />
                  <span>正在加载视频库…</span>
                </div>
              ) : completed.length ? (
                <div className="video-grid">
                  {completed.map((item) => (
                    <button
                      className="video-card"
                      key={item.id}
                      onClick={() => openJob(item)}
                      aria-label={`观看：${item.topic}`}
                    >
                      <VideoThumbnail job={item} token={token} />
                      <div className="video-card-info">
                        <h2>{item.topic}</h2>
                        <span>
                          {timeLabel(item.created_at)}
                          <ArrowRight size={14} />
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              ) : (
                !jobsError && (
                  <div className="empty-state">
                    <div className="empty-illustration">
                      <span />
                      <Video size={34} strokeWidth={1.2} />
                    </div>
                    <h2>你的第一支知识视频，从这里开始</h2>
                    <p>生成完成的视频会自动保存在视频库中。</p>
                    <button className="button-primary" onClick={newVideo}>
                      <Plus size={16} />
                      新建视频
                    </button>
                  </div>
                )
              )}
            </main>
          )}
          {route.view === "history" && !route.id && (
            <main className="collection-page page-enter">
              <div className="page-heading">
                <div>
                  <h1>
                    历史记录<span className="count-badge">{jobs.length}</span>
                  </h1>
                  <p>找到每个想法，以及它成为视频的过程。</p>
                </div>
                <button className="button-primary" onClick={newVideo}>
                  <Plus size={17} />
                  新建视频
                </button>
              </div>
              {jobsError && contentError(jobsError)}
              {jobsLoading ? (
                <div className="collection-loading">
                  <LoaderCircle className="spin" size={22} />
                </div>
              ) : jobs.length ? (
                <div className="history-list">
                  {jobs.map((item) => (
                    <div className="history-record" key={item.id}>
                    <button
                      className="history-row"
                      onClick={() => openJob(item)}
                    >
                      <span className="history-row-icon">
                        {item.status === "succeeded" ? (
                          <Video size={19} />
                        ) : item.status === "failed" ? (
                          <CircleAlert size={19} />
                        ) : (
                          <Workflow size={19} />
                        )}
                      </span>
                      <span className="history-row-copy">
                        <strong>{item.topic}</strong>
                        <span>{timeLabel(item.created_at)}</span>
                      </span>
                      <span className={`status-badge ${item.status}`}>
                        {statusLabels[item.status]}
                      </span>
                      <ChevronRight size={17} />
                    </button>
                    {uiConfig?.can_delete_jobs && (item.status === "succeeded" || item.status === "failed") && (
                      <button className="history-delete-button icon-button" title="删除记录" aria-label={`删除记录：${item.topic}`} onClick={() => setDeleteTarget(item)}><Trash2 size={16} /></button>
                    )}
                    </div>
                  ))}
                </div>
              ) : (
                !jobsError && (
                  <div className="empty-state">
                    <History size={38} strokeWidth={1} />
                    <h2>还没有生成记录</h2>
                    <p>开始一个新视频，制作过程会自动保存在这里。</p>
                    <button className="button-primary" onClick={newVideo}>
                      新建视频
                      <ArrowRight size={16} />
                    </button>
                  </div>
                )
              )}
            </main>
          )}
          {route.view === "history" && route.id && (
            <main className="detail-page production-page page-enter" key={route.id}>
              <div className="detail-heading">
                <button
                  className="button-quiet back-button"
                  onClick={() => navigate({ view: "history" })}
                >
                  <ArrowLeft size={15} />
                  历史记录
                </button>
                {!publicMode && current && stopButton(current)}
                {uiConfig?.can_delete_jobs && current && (current.status === "succeeded" || current.status === "failed") && (
                  <button className="history-detail-delete button-quiet" onClick={() => setDeleteTarget(current)}><Trash2 size={14} />删除记录</button>
                )}
              </div>
              {jobError && contentError(jobError)}
              {!current ? (
                !jobError && (
                  <div className="collection-loading">
                    <LoaderCircle className="spin" size={24} />
                    <span>正在加载创作记录…</span>
                  </div>
                )
              ) : (
                <>
                  <section className="creation-message" aria-label="视频创作主题">
                    <div className="creation-message-label"><span>{publicMode ? "共享创作主题" : "你的创作主题"}</span><time dateTime={current.created_at}>{timeLabel(current.created_at)}</time></div>
                    <div className="creation-message-bubble"><h1>{current.topic}</h1></div>
                    <div className="creation-message-actions">
                      <button className="icon-button" onClick={() => void copyPrompt()} aria-label={copied ? "已复制" : "复制创作描述"}>
                        {copied ? <CheckCheck size={16} /> : <Copy size={16} />}
                      </button>
                    </div>
                  </section>
                  <ProductionPreview key={current.id} job={current} token={token} onNew={newVideo}
                    synchronized={!jobError}
                    process={<TaskProgress key={current.id} job={current} synchronized={!jobError} />}
                    statusContent={<>
                  {current.status === "cancelling" && (
                    <div className="stopped-panel" role="status"><LoaderCircle size={18} className="spin" /><div><h2>正在停止这次制作</h2><p>请等待正在执行的工作结束，完全停止后会自动开放新视频制作。你的草稿会保留。</p></div></div>
                  )}
                  {current.status === "cancelled" && (
                    <div className="stopped-panel"><Square size={18} /><div><h2>这次制作已停止</h2><p>已完成的内容和当前草稿均已保留，可以用下方描述开始新视频。</p><button className="button-secondary" onClick={newVideo}>新建自己的视频<ArrowRight size={15} /></button></div></div>
                  )}
                  {current.status === "failed" && (
                    <div className="failure-panel">
                      <div>
                        <CircleAlert size={20} />
                        <h2>这次生成暂时中断了</h2>
                      </div>
                      <p>已保留完成的步骤，可以从中断处继续。</p>
                      <details>
                        <summary>查看失败原因</summary>
                        <pre>{current.error || "执行失败，请重试。"}</pre>
                      </details>
                      <button
                        className="button-primary"
                        disabled={submitting || generationBlocked}
                        onClick={() => void generate(true)}
                      >
                        {submitting ? (
                          <LoaderCircle size={16} className="spin" />
                        ) : (
                          <RotateCcw size={16} />
                        )}
                        {generationBlocked ? blockedLabel : "继续生成"}
                      </button>
                    </div>
                  )}
                  {submitMode === "resume" && submitError && contentError(submitError, () => void generate(true))}
                    </>} />
                </>
              )}
            </main>
          )}
        </div>
        {(route.view === "new" || Boolean(route.id)) && (
          <CreationComposer prompt={prompt} onPromptChange={setPrompt} onSubmit={() => void generate()}
            submitting={submitting} textareaRef={textarea}
            disabled={generationBlocked} disabledLabel={blockedLabel}
            error={submitMode === "new" && submitError ? contentError(submitError, () => void generate()) : undefined} />
        )}
      </div>
      {uiConfig?.can_delete_jobs && deleteTarget && <DeleteHistoryDialog key={deleteTarget.id} job={deleteTarget} onClose={() => setDeleteTarget(null)} onDelete={deleteHistory} />}
      {uiConfig?.can_cancel_jobs && cancelTarget && <CancelJobDialog key={cancelTarget.id} job={cancelTarget} shared={publicMode} onClose={() => setCancelTarget(null)} onStop={stopJob} />}
      {uiConfig?.can_edit_settings && <ApiSettings
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        token={token}
        onTokenChange={(value) => {
          onTokenChange(value);
          setRefresh((count) => count + 1);
        }}
        onSaved={() => {
          setToast("接口配置已更新，将用于之后开始制作的视频。");
          setRefresh((value) => value + 1);
        }}
      />}
      {toast && (
        <div className="toast-message" role="status">
          <Check size={15} />
          {toast}
        </div>
      )}
    </div>
  );
}
