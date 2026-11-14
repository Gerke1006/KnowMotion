import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Clock3,
  Copy,
  FileText,
  History,
  Library,
  LoaderCircle,
  Menu,
  Plus,
  RotateCcw,
  Settings2,
  Sparkles,
  Video,
  Workflow,
  X,
} from "lucide-react";
import { ApiSettings } from "./components/ApiSettings";
import { Brand, BrandMark } from "./components/Brand";
import { VideoResult, VideoThumbnail } from "./components/StudioMedia";
import {
  api,
  ApiError,
  getDraft,
  readRoute,
  saveDraft,
  stageLabels,
  stages,
  statusLabels,
  timeLabel,
  type Job,
  type StudioRoute,
} from "./studio";

export default function App() {
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
  const [token, setToken] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [processOpen, setProcessOpen] = useState<boolean | null>(null);
  const [copied, setCopied] = useState(false);
  const [toast, setToast] = useState("");
  const pending = useRef(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const workspace = useRef<HTMLDivElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const completed = jobs.filter((item) => item.status === "succeeded");
  const current = job?.id === route.id ? job : null;
  const running = current?.status === "running" || current?.status === "queued";
  const progress = Math.round((current?.progress || 0) * 100);
  const expanded = processOpen ?? current?.status !== "succeeded";
  const activeStage = stages.findIndex((stage) =>
    stage.keys.includes(current?.stage || ""),
  );

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
        setJobs(data.filter((item) => item.mode === "live"));
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
    setProcessOpen(null);
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
        const data: Job = await response.json();
        if (controller.signal.aborted) return;
        setJob(data);
        setJobError("");
        setConnected(true);
        setJobs((previous) =>
          [data, ...previous.filter((item) => item.id !== data.id)].sort(
            (a, b) => b.created_at.localeCompare(a.created_at),
          ),
        );
        if (data.status === "succeeded" || data.status === "failed") return;
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
    url.search = "";
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
  async function generate(resume = false) {
    if (pending.current || (!resume && !prompt.trim()) || (resume && !current))
      return;
    pending.current = true;
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
      const created: Job = await response.json();
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
      setSubmitError(
        error instanceof Error ? error.message : "提交失败，请重试。",
      );
      if (error instanceof ApiError && error.status === 401)
        setSettingsOpen(true);
      if (error instanceof ApiError && error.status === 409)
        setRefresh((value) => value + 1);
    } finally {
      pending.current = false;
      setSubmitting(false);
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
        className="button-quiet"
        onClick={() => {
          if (message.includes("令牌")) setSettingsOpen(true);
          else if (retry) retry();
          else setRefresh((value) => value + 1);
        }}
      >
        重试
      </button>
    </div>
  );

  return (
    <div className={`studio-shell ${sidebarOpen ? "mobile-menu-open" : ""}`}>
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
      <aside ref={sidebarRef} className="sidebar" aria-label="工作空间导航">
        <div className="sidebar-brand">
          <button
            className="brand-button"
            onClick={newVideo}
            aria-label="KnowMotion，开始新视频"
          >
            <Brand />
          </button>
          <button
            className="mobile-close icon-button"
            aria-label="关闭导航"
            onClick={() => setSidebarOpen(false)}
          >
            <X size={19} />
          </button>
        </div>
        <nav className="primary-nav" aria-label="主导航">
          <button
            className={`nav-item ${route.view === "new" ? "active" : ""}`}
            aria-current={route.view === "new" ? "page" : undefined}
            onClick={newVideo}
          >
            <Sparkles size={19} strokeWidth={1.7} />
            <span>New Video</span>
            <Plus className="nav-plus" size={15} />
          </button>
          <button
            className={`nav-item ${route.view === "library" ? "active" : ""}`}
            aria-current={route.view === "library" ? "page" : undefined}
            onClick={() => navigate({ view: "library" })}
          >
            <Library size={19} strokeWidth={1.7} />
            <span>Library</span>
            {completed.length > 0 && (
              <span className="nav-count">{completed.length}</span>
            )}
          </button>
        </nav>
        <div className="history-navigation">
          <div className="sidebar-section-heading">
            <span>HISTORY</span>
            <button
              className={`icon-button ${route.view === "history" && !route.id ? "selected" : ""}`}
              onClick={() => navigate({ view: "history" })}
              aria-label="查看全部历史"
            >
              <History size={15} />
            </button>
          </div>
          {jobsLoading ? (
            <div className="history-loading">
              <span />
              <span />
              <span />
            </div>
          ) : jobs.length === 0 ? (
            <p className="sidebar-empty">
              {jobsError ? "暂时无法加载记录" : "你的创作会留在这里"}
            </p>
          ) : (
            <div className="history-links">
              {jobs.slice(0, 10).map((item) => (
                <button
                  className={`history-link ${route.id === item.id ? "active" : ""}`}
                  key={item.id}
                  onClick={() => openJob(item)}
                  title={item.topic}
                  aria-current={route.id === item.id ? "page" : undefined}
                >
                  <span className={`job-dot ${item.status}`} />
                  <span>{item.topic}</span>
                </button>
              ))}
            </div>
          )}
          {jobs.length > 10 && (
            <button
              className="all-history"
              onClick={() => navigate({ view: "history" })}
            >
              查看全部记录
              <ArrowRight size={13} />
            </button>
          )}
        </div>
        <div className="sidebar-bottom">
          <span className="workspace-avatar">
            <BrandMark />
          </span>
          <div>
            <strong>KnowMotion Studio</strong>
            <span>
              <i className={connected ? "online" : ""} />
              {connected
                ? "工作空间已连接"
                : jobsLoading
                  ? "正在连接工作空间"
                  : "服务未连接"}
            </span>
          </div>
        </div>
      </aside>
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
                ? "Create"
                : route.view === "library"
                  ? "Library"
                  : "History"}
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
          <button
            className="api-settings-button"
            onClick={() => setSettingsOpen(true)}
          >
            <Settings2 size={16} />
            <span>自定义 API</span>
          </button>
        </header>
        <div
          ref={workspace}
          className="workspace-scroll"
          id="main-content"
          tabIndex={-1}
        >
          {route.view === "new" && (
            <main className="create-page page-enter">
              <div className="create-heading">
                <span className="eyebrow">MAKE KNOWLEDGE MOVE</span>
                <h1>What video do you want to create?</h1>
                <p>从一个知识点开始，让理解在画面中发生。</p>
              </div>
              <form
                className="create-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  void generate();
                }}
              >
                <label className="prompt-label" htmlFor="knowledge-prompt">
                  <FileText size={16} />
                  Prompt
                </label>
                <div className="prompt-editor">
                  <textarea
                    ref={textarea}
                    id="knowledge-prompt"
                    value={prompt}
                    maxLength={300}
                    disabled={submitting}
                    placeholder={
                      "输入你想讲解的知识点，或描述你的视频想法…\n\n例如：用直观的动画解释，为什么导数表示瞬时变化率。"
                    }
                    onChange={(event) => setPrompt(event.target.value)}
                    onKeyDown={(event) => {
                      if (
                        (event.ctrlKey || event.metaKey) &&
                        event.key === "Enter" &&
                        !event.nativeEvent.isComposing
                      ) {
                        event.preventDefault();
                        void generate();
                      }
                    }}
                  />
                  <div className="prompt-editor-footer">
                    <span>
                      <Sparkles size={14} />让 Agent 完成讲解、分镜与视频制作
                    </span>
                    <span className="character-count">
                      {prompt.length}
                      <span> / 300</span>
                    </span>
                  </div>
                </div>
                {submitError && contentError(submitError, () => void generate())}
                <div className="generate-toolbar">
                  <span className="keyboard-hint">
                    <kbd>Ctrl</kbd>
                    <span>+</span>
                    <kbd>Enter</kbd>
                    <span>快速生成</span>
                  </span>
                  <button
                    className="button-primary generate-button"
                    disabled={!prompt.trim() || submitting}
                    type="submit"
                  >
                    {submitting ? (
                      <>
                        <LoaderCircle size={17} className="spin" />
                        Creating…
                      </>
                    ) : (
                      <>
                        Generate Video
                        <ArrowRight size={18} />
                      </>
                    )}
                  </button>
                </div>
              </form>
            </main>
          )}
          {route.view === "library" && (
            <main className="collection-page page-enter">
              <div className="page-heading">
                <div>
                  <h1>
                    Library
                    <span className="count-badge">{completed.length}</span>
                  </h1>
                  <p>每一次理解，都值得留下。</p>
                </div>
                <button className="button-primary" onClick={newVideo}>
                  <Plus size={17} />
                  Create video
                </button>
              </div>
              <div className="collection-tabs">
                <span>
                  <Video size={17} />
                  Videos
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
                    <p>生成完成的视频会自动出现在 Library 中。</p>
                    <button className="button-primary" onClick={newVideo}>
                      <Plus size={16} />
                      Create video
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
                    History<span className="count-badge">{jobs.length}</span>
                  </h1>
                  <p>找到每个想法，以及它成为视频的过程。</p>
                </div>
                <button className="button-primary" onClick={newVideo}>
                  <Plus size={17} />
                  New video
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
                    <button
                      className="history-row"
                      key={item.id}
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
                  ))}
                </div>
              ) : (
                !jobsError && (
                  <div className="empty-state">
                    <History size={38} strokeWidth={1} />
                    <h2>还没有生成记录</h2>
                    <p>开始一个新视频，制作过程会自动保存在这里。</p>
                    <button className="button-primary" onClick={newVideo}>
                      New Video
                      <ArrowRight size={16} />
                    </button>
                  </div>
                )
              )}
            </main>
          )}
          {route.view === "history" && route.id && (
            <main className="detail-page page-enter" key={route.id}>
              <div className="detail-heading">
                <button
                  className="button-quiet back-button"
                  onClick={() => navigate({ view: "history" })}
                >
                  <ArrowLeft size={15} />
                  History
                </button>
                <h1>Your idea, in motion.</h1>
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
                  <section className="prompt-message" aria-label="视频创作描述">
                    <div className="message-date">
                      {timeLabel(current.created_at)}
                    </div>
                    <div className="message-bubble">{current.topic}</div>
                    <button
                      className="icon-button copy-prompt"
                      onClick={() => void copyPrompt()}
                      aria-label={copied ? "已复制" : "复制 Prompt"}
                    >
                      {copied ? <CheckCheck size={16} /> : <Copy size={16} />}
                    </button>
                  </section>
                  <section
                    className={`process-card ${expanded ? "expanded" : ""}`}
                  >
                    <button
                      className="process-toggle"
                      aria-expanded={expanded}
                      aria-controls="production-process"
                      onClick={() => setProcessOpen(!expanded)}
                    >
                      <span className={`process-symbol ${current.status}`}>
                        {running ? (
                          <LoaderCircle size={18} className="spin" />
                        ) : current.status === "succeeded" ? (
                          <Check size={18} />
                        ) : (
                          <Workflow size={18} />
                        )}
                      </span>
                      <span className="process-toggle-copy">
                        <strong>制作流程</strong>
                        <span aria-live="polite">
                          {current.status === "succeeded"
                            ? "所有阶段已完成"
                            : current.status === "failed"
                              ? "生成暂时中断，可以继续此任务"
                              : stageLabels[current.stage] || "正在处理"}
                        </span>
                      </span>
                      <span className="process-percentage">{progress}%</span>
                      <ChevronDown
                        size={17}
                        className={expanded ? "rotated" : ""}
                      />
                    </button>
                    {expanded && (
                      <div id="production-process" className="process-body">
                        <div
                          className="process-progress"
                          role="progressbar"
                          aria-label="制作进度"
                          aria-valuenow={progress}
                          aria-valuemin={0}
                          aria-valuemax={100}
                        >
                          <span style={{ width: `${progress}%` }} />
                        </div>
                        <ol className="production-steps">
                          {stages.map((stage, index) => {
                            const done =
                              current.status === "succeeded" ||
                              index < activeStage;
                            const active =
                              index === activeStage &&
                              current.status !== "succeeded";
                            return (
                              <li
                                key={stage.name}
                                className={`${done ? "step-done" : ""} ${active ? "step-active" : ""}`}
                                aria-current={active ? "step" : undefined}
                              >
                                <span className="step-marker">
                                  {done ? (
                                    <Check size={13} />
                                  ) : active && running ? (
                                    <span />
                                  ) : (
                                    index + 1
                                  )}
                                </span>
                                <span className="step-content">
                                  <strong>{stage.name}</strong>
                                  <span>{stage.detail}</span>
                                </span>
                                <span className="step-label">
                                  {done
                                    ? "完成"
                                    : active
                                      ? current.status === "failed"
                                        ? "中断"
                                        : "进行中"
                                      : "等待中"}
                                </span>
                              </li>
                            );
                          })}
                        </ol>
                        <div className="process-footnote">
                          <Clock3 size={13} />
                          {running
                            ? "任务在后台持续进行，稍后可从 History 返回查看。"
                            : current.status === "succeeded"
                              ? "讲稿、画面、字幕与配音已生成。"
                              : "完成的步骤已保存，继续时将复用有效结果。"}
                        </div>
                      </div>
                    )}
                  </section>
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
                        disabled={submitting}
                        onClick={() => void generate(true)}
                      >
                        {submitting ? (
                          <LoaderCircle size={16} className="spin" />
                        ) : (
                          <RotateCcw size={16} />
                        )}
                        继续生成
                      </button>
                    </div>
                  )}
                  {submitError && contentError(submitError, () => void generate(true))}
                  {current.status === "succeeded" ? (
                    <VideoResult
                      key={current.id}
                      job={current}
                      token={token}
                      onNew={newVideo}
                    />
                  ) : (
                    running && (
                      <div className="producing-preview">
                        <div className="producing-orbit">
                          <BrandMark />
                        </div>
                        <h2>让知识，一帧帧动起来。</h2>
                        <p>
                          {stageLabels[current.stage] || "正在制作"}
                          <span className="animated-ellipsis">…</span>
                        </p>
                        <span className="producing-caption">
                          <Video size={14} />
                          完成后，视频会出现在这里
                        </span>
                      </div>
                    )
                  )}
                </>
              )}
            </main>
          )}
        </div>
      </div>
      <ApiSettings
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        token={token}
        onTokenChange={(value) => {
          setToken(value);
          setRefresh((count) => count + 1);
        }}
        onSaved={() => {
          setToast("API 配置已更新，将用于之后开始制作的视频。");
          setRefresh((value) => value + 1);
        }}
      />
      {toast && (
        <div className="toast-message" role="status">
          <Check size={15} />
          {toast}
        </div>
      )}
    </div>
  );
}
