import { stageLabels, type Job } from "../studio";
import { BrandMark } from "./Brand";

export function GenerationPlaceholder({ job, synchronized = true }: { job: Job; synchronized?: boolean }) {
  const running = job.status === "running" || job.status === "queued";
  const waiting = !synchronized;
  const queued = job.status === "queued";
  const failed = job.status === "failed";
  const cancelling = job.status === "cancelling";
  const cancelled = job.status === "cancelled";
  const progress = Number.isFinite(job.progress)
    ? Math.round(Math.min(1, Math.max(0, job.progress)) * 100)
    : null;
  const showProgress = !waiting && job.status === "running" && progress !== null;
  const status = waiting ? "等待同步" : cancelling ? "正在停止" : cancelled ? "已停止" : queued ? "排队中" : failed ? "未完成" : "制作进度";
  const title = waiting ? "正在重新连接" : cancelling ? "正在停止视频制作" : cancelled ? "这次制作已停止" : queued ? "等待开始制作" : failed ? "视频尚未完成" : "视频正在生成";
  const description = waiting ? "连接恢复后，制作状态会继续更新。"
    : cancelling ? "正在结束制作工作，完全停止后即可创建新视频。"
      : cancelled ? "已有内容会保留，可以开始新的创作。"
    : queued ? "任务已进入制作队列。"
      : failed ? "已完成的制作内容会保留。"
        : stageLabels[job.stage] || "正在制作";
  const state = waiting ? "waiting" : cancelling ? "cancelling" : cancelled ? "cancelled" : queued ? "queued" : failed ? "failed" : "running";

  return (
    <div className={`generation-placeholder is-${state}`} aria-label="视频生成预览">
      <div className="generation-placeholder-status" role="status" aria-live="polite">
        <span className="generation-placeholder-status-dot" aria-hidden="true" />
        <span>{status}</span>
        {showProgress && <strong>{progress}%</strong>}
      </div>
      <div className="generation-placeholder-center">
        <div className="generation-placeholder-mark"><BrandMark animated={running && synchronized} /></div>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      <span className="generation-placeholder-caption">{cancelled ? "停止记录与已完成的制作内容会保留" : cancelling ? "正在停止，请稍等" : "完成后，视频将在这里播放"}</span>
    </div>
  );
}
