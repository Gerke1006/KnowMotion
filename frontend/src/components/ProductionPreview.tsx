import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Check, ChevronDown, Film, Image, Layers3, Play, RotateCcw } from "lucide-react";
import { api, type Job } from "../studio";
import { GenerationPlaceholder } from "./GenerationPlaceholder";
import { useProtectedMedia, VideoResult } from "./StudioMedia";

type Scene = {
  id: string;
  index: number;
  title: string;
  narration: string;
  visual_description: string;
  state: "planned" | "ready";
  image_url: string | null;
  video_url: string | null;
};
type Production = { title: string | null; script_excerpt: string | null; scenes: Scene[]; previews_pending?: boolean };

function SceneCard({ scene, token, selected, onSelect }: {
  scene: Scene; token: string; selected: boolean; onSelect: () => void;
}) {
  const image = useProtectedMedia(scene.image_url, token);
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [image.src]);
  return (
    <button className={`scene-card ${selected ? "selected" : ""}`} onClick={onSelect}
      aria-pressed={selected} aria-label={`分镜 ${scene.index}，${scene.title}，${scene.state === "ready" ? "可查看画面" : "已编排"}`}>
      <span className="scene-card-thumb">
        {image.src && !image.error && !broken
          ? <img src={image.src} alt="" loading="lazy" onError={() => setBroken(true)} />
          : <span className="scene-card-paper"><span>{String(scene.index).padStart(2, "0")}</span><Layers3 size={20} strokeWidth={1.3} /></span>}
        <span className="scene-card-number">{String(scene.index).padStart(2, "0")}</span>
      </span>
      <span className="scene-card-copy"><strong>{scene.title}</strong>
        <span className={`scene-state ${scene.state}`}>
          {scene.state === "ready" ? <><Check size={12} />画面可查看</> : <><Film size={12} />分镜已编排</>}
        </span>
      </span>
    </button>
  );
}

function SceneView({ scene, token, active, onEngage }: { scene: Scene; token: string; active: boolean; onEngage: () => void }) {
  const [play, setPlay] = useState(false);
  const player = useRef<HTMLVideoElement>(null);
  const [mediaFailed, setMediaFailed] = useState(false);
  const image = useProtectedMedia(scene.image_url, token);
  const video = useProtectedMedia(play ? scene.video_url : null, token);
  useEffect(() => setMediaFailed(false), [image.src, video.src]);
  useEffect(() => {
    if (!active) {
      player.current?.pause();
      setPlay(false);
    }
  }, [active]);
  return (
    <>
      <div className="production-canvas">
        <div className="scene-stage">
          {play && video.src && !mediaFailed ? (
            <video ref={player} src={video.src} poster={image.src || undefined} controls playsInline autoPlay
              aria-label={`分镜 ${scene.index} 画面片段`} onError={() => setMediaFailed(true)} />
          ) : image.src && !image.error && !mediaFailed ? (
            <img src={image.src} alt={`分镜 ${scene.index}：${scene.title}`} onError={() => setMediaFailed(true)} />
          ) : (
            <div className="scene-script">
              <span className="scene-script-index"><Layers3 size={15} />分镜 {String(scene.index).padStart(2, "0")}</span>
              <h3>{scene.title}</h3>
              <p>{scene.narration || scene.visual_description || "该分镜已编排，画面将在渲染完成后出现。"}</p>
              <span className="scene-script-caption">
                {scene.state === "ready" ? "已生成画面，可查看片段" : "分镜已编排 · 画面生成后将在这里展示"}
              </span>
            </div>
          )}
          {!play && scene.video_url && (
            <button className="scene-play-button" onClick={() => { onEngage(); setPlay(true); }}><Play size={16} fill="currentColor" />播放当前片段</button>
          )}
        </div>
        <div className="scene-preview-caption">
          <span><Image size={14} />{play ? "场景片段" : image.src && !mediaFailed ? "真实画面预览" : "分镜讲解"}</span>
          <span>分镜 {scene.index} · {scene.title}</span>
        </div>
      </div>
      {(video.error || image.error || mediaFailed) && (
        <div className="production-update-error" role="status">
          画面暂时无法加载，分镜内容仍可查看。
          <button onClick={() => { setMediaFailed(false); image.retry(); video.retry(); }}><RotateCcw size={13} />重新加载</button>
        </div>
      )}
      <details className="scene-notes">
        <summary>查看分镜讲解与画面描述<ChevronDown size={14} /></summary>
        {scene.narration && <div><span>讲解内容</span><p>{scene.narration}</p></div>}
        {scene.visual_description && <div><span>画面描述</span><p>{scene.visual_description}</p></div>}
        {!scene.narration && !scene.visual_description && <p>此分镜未记录文字说明。</p>}
      </details>
    </>
  );
}

export function ProductionPreview({ job, token, onNew, process, statusContent, synchronized = true }: {
  job: Job; token: string; onNew: () => void; process?: ReactNode; statusContent?: ReactNode; synchronized?: boolean;
}) {
  const [production, setProduction] = useState<Production | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showScenes, setShowScenes] = useState<boolean | null>(null);
  const revealId = useId();
  const running = job.status === "queued" || job.status === "running" || job.status === "cancelling";
  const complete = job.status === "succeeded";

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      let previewsPending = false;
      try {
        const response = await api(`/jobs/${encodeURIComponent(job.id)}/production`, token, { signal: controller.signal });
        const data: Production = await response.json();
        if (controller.signal.aborted) return;
        previewsPending = Boolean(data.previews_pending);
        setProduction(data);
        setError("");
      } catch (problem) {
        if (controller.signal.aborted) return;
        setError(problem instanceof Error ? problem.message : "暂时无法更新制作画面。");
      }
      if (!controller.signal.aborted && (running || previewsPending)) timer = setTimeout(load, 2500);
    };
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [job.id, job.status, token, retry, running]);

  const scenes = production?.scenes || [];
  // Surface the first actual frame as soon as it is available. Explicit scene
  // selections (including playback) stay fixed across subsequent snapshots.
  const selected = scenes.find((scene) => scene.id === selectedId) || scenes.find((scene) => scene.state === "ready") || scenes[0];
  const ready = scenes.filter((scene) => scene.state === "ready").length;
  const visible = showScenes ?? !complete;
  const hasScenesContent = scenes.length > 0 || Boolean(production?.script_excerpt);

  return (
    <section className={`production-work ${complete ? "is-complete" : ""}`} aria-label="视频制作成果">
      <div className="production-primary-stage">
        {complete ? (
          <div className="production-final-result"><VideoResult job={job} token={token} onNew={onNew} /></div>
        ) : <GenerationPlaceholder job={job} synchronized={synchronized} />}
      </div>
      {process && <div className="production-process-slot">{process}</div>}
      {statusContent && <div className="production-status-slot">{statusContent}</div>}
      {error && <div className="production-update-error" role="status">
        <span>{error} {running && "正在尝试重新连接，任务状态以制作进度为准。"}</span>
        <button onClick={() => setRetry((value) => value + 1)}><RotateCcw size={13} />重试</button>
      </div>}
      {hasScenesContent && <section className="production-scenes-section" aria-label="制作中的分镜与讲解">
        <button className="production-scenes-toggle" aria-expanded={visible} aria-controls={revealId} onClick={() => setShowScenes(!visible)}>
          <Layers3 size={16} />
          <span>{scenes.length ? complete ? "回看制作分镜" : "制作分镜" : "讲解内容"}</span>
          {scenes.length > 0 && <small aria-live="polite">{scenes.length} 个分镜 · {ready} 个画面就绪</small>}
          <ChevronDown size={16} className={visible ? "rotated" : ""} />
        </button>
        <div className="task-disclosure production-reveal" data-open={visible} id={revealId} inert={!visible} aria-hidden={!visible}>
          <div className="task-disclosure-inner">
          {selected ? (
            <>
              <SceneView key={selected.id} scene={selected} token={token} active={visible} onEngage={() => setSelectedId(selected.id)} />
              <div className="scene-strip" aria-label="分镜列表">
                {scenes.map((scene) => <SceneCard key={scene.id} scene={scene} token={token} selected={scene.id === selected.id} onSelect={() => setSelectedId(scene.id)} />)}
              </div>
            </>
          ) : production?.script_excerpt && (
            <div className="production-script-summary">
              <span className="production-empty-label"><Film size={16} />讲解内容已就绪</span>
              <h3>{production.title || "讲解正在转化为分镜"}</h3>
              <p className="production-script-excerpt">{production.script_excerpt}</p>
              <small>{running ? "分镜编排完成后会出现在这里。" : "已保留生成的讲解内容。"}</small>
            </div>
          )}
          </div>
        </div>
      </section>}
    </section>
  );
}
