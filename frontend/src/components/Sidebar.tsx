import {
  useLayoutEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type CSSProperties,
  type RefObject,
} from "react";
import { ArrowRight, ArrowUpRight, ChevronRight, CircleAlert, FileVideo, History, Library, LoaderCircle, Plus, Square, Trash2, X } from "lucide-react";
import { Brand, BrandMark } from "./Brand";
import { statusLabels, timeLabel, type Job, type StudioRoute } from "../studio";

type Ripple = { id: number; x: number; y: number; size: number };

function SidebarButton({ children, className = "", onPointerDown, onPointerMove, onClick, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  const [ripples, setRipples] = useState<Ripple[]>([]);
  const nextId = useRef(0);

  function illuminate(button: HTMLButtonElement, point?: { x: number; y: number }) {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const rect = button.getBoundingClientRect();
    const ripple = {
      id: nextId.current++,
      x: point ? point.x - rect.left : rect.width / 2,
      y: point ? point.y - rect.top : rect.height / 2,
      size: Math.hypot(rect.width, rect.height) * 2,
    };
    setRipples((previous) => [...previous.slice(-2), ripple]);
  }

  return (
    <button {...props} type={props.type || "button"} className={`sidebar-control ${className}`}
      onPointerDown={(event) => {
        if (event.button === 0) illuminate(event.currentTarget, { x: event.clientX, y: event.clientY });
        onPointerDown?.(event);
      }}
      onPointerMove={(event) => {
        if (event.pointerType === "mouse") {
          const rect = event.currentTarget.getBoundingClientRect();
          event.currentTarget.style.setProperty("--pointer-x", `${event.clientX - rect.left}px`);
          event.currentTarget.style.setProperty("--pointer-y", `${event.clientY - rect.top}px`);
        }
        onPointerMove?.(event);
      }}
      onClick={(event) => {
        if (event.detail === 0) illuminate(event.currentTarget);
        onClick?.(event);
      }}>
      {children}
      {ripples.map((ripple) => (
        <span key={ripple.id} className="sidebar-ripple" aria-hidden="true"
          style={{ "--ripple-x": `${ripple.x}px`, "--ripple-y": `${ripple.y}px`, "--ripple-size": `${ripple.size}px` } as CSSProperties}
          onAnimationEnd={() => setRipples((previous) => previous.filter((item) => item.id !== ripple.id))} />
      ))}
    </button>
  );
}

function SidebarNavigation({ view, completed, onNavigate }: {
  view: StudioRoute["view"];
  completed: number;
  onNavigate: (route: StudioRoute) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [selection, setSelection] = useState({ y: 0, height: 48 });
  useLayoutEffect(() => {
    const measure = () => {
      const active = container.current?.querySelector<HTMLButtonElement>('[aria-current="page"]');
      if (active) setSelection({ y: active.offsetTop, height: active.offsetHeight });
    };
    measure();
    const observer = new ResizeObserver(measure);
    if (container.current) observer.observe(container.current);
    return () => observer.disconnect();
  }, [view]);
  return (
    <nav className="primary-nav" aria-label="主导航">
      <span className="sidebar-nav-label">工作空间</span>
      <div className="sidebar-nav-items" ref={container}>
        <span className={`sidebar-selection ${view !== "new" ? "is-visible" : ""}`} aria-hidden="true"
          style={{ transform: `translateY(${selection.y}px)`, height: selection.height }} />
        <SidebarButton className={`nav-item ${view === "library" ? "active" : ""}`}
          aria-current={view === "library" ? "page" : undefined} onClick={() => onNavigate({ view: "library" })}>
          <span className="nav-icon"><Library size={19} strokeWidth={1.7} /></span><span>视频库</span>
          {completed > 0 && <span className="nav-count">{completed}</span>}
        </SidebarButton>
        <SidebarButton className={`nav-item ${view === "history" ? "active" : ""}`}
          aria-current={view === "history" ? "page" : undefined} onClick={() => onNavigate({ view: "history" })}>
          <span className="nav-icon"><History size={19} strokeWidth={1.7} /></span><span>历史记录</span>
          <ChevronRight className="nav-trailing" size={14} />
        </SidebarButton>
      </div>
    </nav>
  );
}

export function Sidebar({ sidebarRef, route, jobs, jobsLoading, jobsError, connected, onHome, onNew, onNavigate, onOpenJob, onDeleteJob, onClose }: {
  sidebarRef: RefObject<HTMLElement | null>;
  route: StudioRoute;
  jobs: Job[];
  jobsLoading: boolean;
  jobsError: string;
  connected: boolean;
  onHome: () => void;
  onNew: () => void;
  onNavigate: (route: StudioRoute) => void;
  onOpenJob: (job: Job) => void;
  onDeleteJob?: (job: Job) => void;
  onClose: () => void;
}) {
  return (
    <aside ref={sidebarRef} className="sidebar" aria-label="工作空间导航">
      <div className="sidebar-brand">
        <button type="button" className="brand-button" onClick={onHome} aria-label="KnowMotion，返回首页"><Brand /></button>
        <button type="button" className="mobile-close icon-button" aria-label="关闭导航" onClick={onClose}><X size={18} /></button>
      </div>
      <SidebarButton className={`sidebar-create ${route.view === "new" ? "is-current" : ""}`}
        aria-current={route.view === "new" ? "page" : undefined} onClick={onNew}>
        <span className="create-symbol"><Plus size={20} strokeWidth={1.8} /></span>
        <span className="create-copy"><strong>新建视频</strong><small>让一个想法开始</small></span>
        <ArrowUpRight size={17} strokeWidth={1.6} />
      </SidebarButton>
      <SidebarNavigation view={route.view} completed={jobs.filter((item) => item.status === "succeeded").length} onNavigate={onNavigate} />
      <div className="history-navigation">
        <div className="sidebar-section-heading">
          <span>最近创作</span>
          <SidebarButton className="icon-button" onClick={() => onNavigate({ view: "history" })} aria-label="查看全部历史" title="查看全部历史"><ArrowUpRight size={15} /></SidebarButton>
        </div>
        {jobsLoading ? <div className="history-loading" aria-label="正在加载最近创作"><span /><span /><span /></div>
          : jobs.length === 0 ? <p className="sidebar-empty">{jobsError ? "暂时无法加载记录" : "你的第一份创作，从这里开始。"}</p>
            : <div className="history-links">
              {jobs.slice(0, 10).map((item) => (
                <div className="sidebar-history-record" key={item.id}>
                <SidebarButton className={`history-link ${route.id === item.id ? "active" : ""}`} data-status={item.status}
                  onClick={() => onOpenJob(item)} title={item.topic} aria-current={route.id === item.id ? "page" : undefined}>
                  <span className={`history-entry-icon ${item.status}`}>
                    {item.status === "running" || item.status === "queued" || item.status === "cancelling" ? <LoaderCircle size={15} className="spin" />
                      : item.status === "cancelled" ? <Square size={15} /> : item.status === "failed" ? <CircleAlert size={15} /> : <FileVideo size={15} />}
                  </span>
                  <span className="history-entry-copy"><span>{item.topic}</span><small>{timeLabel(item.created_at)}<i />{statusLabels[item.status]}</small></span>
                </SidebarButton>
                {onDeleteJob && (item.status === "succeeded" || item.status === "failed") && (
                  <button className="sidebar-history-delete icon-button" title="删除记录" aria-label={`删除记录：${item.topic}`} onClick={() => onDeleteJob(item)}><Trash2 size={14} /></button>
                )}
                </div>
              ))}
            </div>}
        {jobs.length > 10 && <SidebarButton className="all-history" onClick={() => onNavigate({ view: "history" })}>查看全部记录<ArrowRight size={13} /></SidebarButton>}
      </div>
      <div className="sidebar-bottom">
        <span className="workspace-avatar"><BrandMark /></span>
        <div><strong>知动创作空间</strong><span><i className={connected ? "online" : ""} />{connected ? "制作服务已连接" : jobsLoading ? "正在连接制作服务" : "服务未连接"}</span></div>
      </div>
    </aside>
  );
}
