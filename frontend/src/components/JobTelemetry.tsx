import { useEffect, useState } from "react";
import type { Job, StageTelemetry, TokenUsage } from "../studio";

const numberFormat = new Intl.NumberFormat("zh-CN");
const hasNumber = (value: number | null | undefined): value is number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0;
const tokenLabel = (value: number | null | undefined) =>
  hasNumber(value) ? numberFormat.format(value) : "未返回";

function timeText(value: number | null | undefined) {
  if (!hasNumber(value)) return "未记录";
  const seconds = Math.floor(value / 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  if (hours) return `${hours}小时${String(minutes).padStart(2, "0")}分${String(rest).padStart(2, "0")}秒`;
  if (minutes) return `${minutes}分${String(rest).padStart(2, "0")}秒`;
  return `${rest}秒`;
}

function useSnapshotDelta(job: Job) {
  const [now, setNow] = useState(() => performance.now());
  const telemetry = job.telemetry;
  const active = Boolean(
    telemetry?.timing_recorded &&
      ((job.status === "running" && telemetry.running) ||
        (job.status === "queued" && telemetry.queued)),
  );
  useEffect(() => {
    setNow(performance.now());
    if (!active) return;
    const interval = window.setInterval(() => setNow(performance.now()), 1000);
    return () => window.clearInterval(interval);
  }, [job.id, job.telemetryReceivedAt, active]);
  // Backend elapsed already includes time through as_of. Count only time since
  // receiving that snapshot, avoiding server/client wall-clock differences.
  if (!active || !telemetry?.as_of || !hasNumber(job.telemetryReceivedAt)) return 0;
  return Math.max(0, now - job.telemetryReceivedAt);
}

function advancing(value: number | null | undefined, delta: number, active: boolean) {
  return hasNumber(value) ? value + (active ? delta : 0) : null;
}

function UsageDetails({ usage }: { usage?: TokenUsage }) {
  return (
    <details className="usage-breakdown">
      <summary>查看用量细分</summary>
      <dl>
        <div><dt>推理词元</dt><dd>{tokenLabel(usage?.reasoning_tokens)}</dd></div>
        <div><dt>缓存输入词元</dt><dd>{tokenLabel(usage?.cached_input_tokens)}</dd></div>
        <div><dt>已结束调用</dt><dd>{usage ? numberFormat.format(usage.calls) : "未记录"}</dd></div>
      </dl>
      <p>推理和缓存用量是输入、输出的细分，不重复计入总量。</p>
    </details>
  );
}

export function JobMetrics({ job }: { job: Job }) {
  const delta = useSnapshotDelta(job);
  const telemetry = job.telemetry;
  const recorded = telemetry?.timing_recorded;
  const elapsed = recorded && telemetry
    ? advancing(telemetry.elapsed_ms, delta, job.status === "running" && telemetry.running)
    : null;
  const queue = recorded && telemetry
    ? advancing(telemetry.queue_ms, delta, job.status === "queued" && telemetry.queued)
    : null;
  const usage = telemetry?.usage;
  const missing = usage?.unreported_calls || 0;
  return (
    <section className="job-metrics" aria-label="任务用量与耗时">
      <dl className="job-metric-grid">
        <div><dt>输入词元</dt><dd>{tokenLabel(usage?.input_tokens)}</dd></div>
        <div><dt>输出词元</dt><dd>{tokenLabel(usage?.output_tokens)}</dd></div>
        <div><dt>总执行时间</dt><dd>{timeText(elapsed)}</dd></div>
        <div><dt>排队时间</dt><dd>{timeText(queue)}</dd></div>
      </dl>
      <div className="job-metric-notes">
        <p>
          总执行时间不含排队和中断等待。
          {!recorded && " 此任务未记录执行耗时。"}
          {missing > 0 && ` ${missing} 次调用未返回完整用量，当前显示已返回部分。`}
        </p>
        <UsageDetails usage={usage} />
      </div>
    </section>
  );
}

const phaseRows = [
  { id: "identify", name: "理解主题" },
  { id: "research", name: "检索与研究" },
  { id: "teaching", name: "生成讲稿" },
  { id: "assets", name: "匹配素材" },
  { id: "visual", name: "导演与画面规划" },
  { id: "storyboard", name: "编排分镜" },
  { id: "generation", name: "生成场景" },
  { id: "rendering", name: "视频制作" },
  { id: "narration", name: "配音", child: true },
  { id: "animation", name: "动画渲染", child: true },
  { id: "composition", name: "最终合成", child: true },
];
const phaseStatus: Record<StageTelemetry["status"], string> = {
  running: "进行中", completed: "已完成", failed: "失败", cached: "缓存复用", interrupted: "已中断",
};

export function StageMetrics({ job }: { job: Job }) {
  const delta = useSnapshotDelta(job);
  const telemetry = job.telemetry;
  const records = telemetry?.stages || {};
  const known = new Set(phaseRows.map((row) => row.id));
  const rows = [
    ...phaseRows,
    ...Object.keys(records).filter((id) => !known.has(id)).map((id) => ({ id, name: id, child: false })),
  ];
  const terminal = job.status === "succeeded" || job.status === "failed" || job.status === "cancelled";
  return (
    <div className="stage-metrics">
      <div className="stage-metrics-scroll" role="region" aria-label="各阶段耗时与词元用量" tabIndex={0}>
        <table>
          <thead><tr><th scope="col">制作阶段</th><th scope="col">状态</th><th scope="col">耗时</th><th scope="col">输入词元</th><th scope="col">输出词元</th></tr></thead>
          <tbody>
            {rows.map((row) => {
              const stage = records[row.id];
              const active = Boolean(job.status === "running" && telemetry?.running && stage?.status === "running");
              const duration = advancing(stage?.elapsed_ms, delta, active);
              const status = stage
                ? phaseStatus[stage.status]
                : !telemetry?.timing_recorded || terminal ? "未记录" : "待开始";
              return (
                <tr key={row.id} className={`${row.child ? "stage-metric-child" : ""} ${active ? "stage-metric-active" : ""}`}>
                  <th scope="row">
                    <span className="stage-metric-name">{row.name}</span>
                    {stage && stage.attempts > 1 && <small>执行 {stage.attempts} 次</small>}
                    {stage && stage.cached_runs > 0 && stage.status !== "cached" && <small>复用缓存 {stage.cached_runs} 次</small>}
                    {stage && stage.calls > 0 && <UsageDetails usage={stage} />}
                  </th>
                  <td><span className={`stage-metric-status ${stage?.status || "unrecorded"}`}>{status}</span></td>
                  <td className="stage-metric-number">{timeText(duration)}</td>
                  <td className="stage-metric-number">{tokenLabel(stage?.input_tokens)}</td>
                  <td className="stage-metric-number">{tokenLabel(stage?.output_tokens)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="stage-metric-note">阶段可能并行或嵌套，耗时不能直接相加。词元仅累计供应商已返回的用量，缺失部分不估算。</p>
    </div>
  );
}
