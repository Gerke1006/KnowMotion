import { useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  LoaderCircle,
  Play,
  RotateCcw,
  Video,
} from "lucide-react";
import { api, durationLabel, type Job } from "../studio";

function useProtectedMedia(path: string | null, token: string) {
  const [src, setSrc] = useState("");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    setSrc("");
    setError("");
    if (!path) return;
    if (!token) {
      setSrc(path);
      return;
    }
    const controller = new AbortController();
    let blobUrl = "";
    void api(path, token, { signal: controller.signal }, 120000)
      .then((response) => response.blob())
      .then((blob) => {
        if (controller.signal.aborted) return;
        blobUrl = URL.createObjectURL(blob);
        setSrc(blobUrl);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError("加载失败，请重试。");
      });
    return () => {
      controller.abort();
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [path, token, attempt]);
  return { src, error, retry: () => setAttempt((value) => value + 1) };
}

export function VideoThumbnail({ job, token }: { job: Job; token: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "100px" },
    );
    if (host.current) observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  const { src, error } = useProtectedMedia(
    visible ? `/jobs/${encodeURIComponent(job.id)}/thumbnail` : null,
    token,
  );
  useEffect(() => {
    setFailed(false);
  }, [src]);
  return (
    <div ref={host} className="video-thumbnail">
      {src && !failed && !error ? (
        <img src={src} alt="" loading="lazy" onError={() => setFailed(true)} />
      ) : (
        <div className="thumbnail-placeholder">
          <Video size={32} strokeWidth={1.2} />
          <span>{failed || error ? "预览暂不可用" : "正在加载预览"}</span>
        </div>
      )}
      <span className="thumbnail-play">
        <Play size={19} fill="currentColor" />
      </span>
      <span className="thumbnail-format">MP4</span>
    </div>
  );
}

export function VideoResult({
  job,
  token,
  onNew,
}: {
  job: Job;
  token: string;
  onNew: () => void;
}) {
  const video = useProtectedMedia(
    `/jobs/${encodeURIComponent(job.id)}/video`,
    token,
  );
  const poster = useProtectedMedia(
    `/jobs/${encodeURIComponent(job.id)}/thumbnail`,
    token,
  );
  const [duration, setDuration] = useState(0);
  const [playError, setPlayError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => { setPlayError(false); setDuration(0); }, [video.src]);
  return (
    <section className="video-result" aria-label="生成的视频">
      <div className="result-section-heading">
        <h2>{job.topic}</h2>
        <span className="finished-label">Ready to watch</span>
      </div>
      <div className="video-player-wrap">
        {video.src && !playError ? (
          <video
            key={attempt}
            src={video.src}
            poster={poster.src || undefined}
            controls
            playsInline
            preload="metadata"
            aria-label={`${job.topic}，生成的视频`}
            onLoadedMetadata={(event) =>
              setDuration(event.currentTarget.duration)
            }
            onError={() => setPlayError(true)}
          />
        ) : (
          <div className="player-message">
            {video.error || playError ? (
              <>
                <Video size={30} />
                <p>视频暂时无法播放</p>
                <button
                  className="button-secondary"
                  onClick={() => {
                    video.retry();
                    setPlayError(false);
                    setAttempt((value) => value + 1);
                  }}
                >
                  <RotateCcw size={15} />
                  重新加载
                </button>
              </>
            ) : (
              <>
                <LoaderCircle className="spin" size={25} />
                <p>正在加载视频…</p>
              </>
            )}
          </div>
        )}
      </div>
      <div className="result-actions">
        <div className="download-actions">
          {video.src && (
            <a
              className="button-secondary download-link"
              href={video.src}
              download="knowmotion-video.mp4"
            >
              <ArrowDownToLine size={17} />
              Download
            </a>
          )}
          <button className="button-primary" onClick={onNew}>
            Create new video
          </button>
        </div>
        <span className="result-meta">
          {duration > 0 ? `${durationLabel(duration)} · ` : ""}MP4
        </span>
      </div>
    </section>
  );
}
