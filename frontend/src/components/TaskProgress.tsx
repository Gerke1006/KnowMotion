import { useEffect, useId, useState, type ReactNode } from "react";
import { Check, ChevronDown, Circle, CircleAlert, Pause, Square } from "lucide-react";
import { stageLabels, type Job, type StageTelemetry, type TokenUsage } from "../studio";
import { costLabel, estimateTextCost, isRecordedNumber } from "../productionCost";
import { BrandMark } from "./Brand";

type Phase = { id: string; name: string; description: string; child?: boolean };
const phases: Phase[] = [
  { id: "identify", name: "理解主题", description: "识别知识点所属学科，明确这次讲解的目标。" },
  { id: "research", name: "检索与研究", description: "检索相关资料，整理讲解需要的概念与依据。" },
  { id: "teaching", name: "生成讲稿", description: "组织讲解顺序，将知识点转化为清晰的旁白。" },
  { id: "visual", name: "导演与画面规划", description: "为讲解安排画面、可见对象和动画表达。" },
  { id: "assets", name: "匹配素材", description: "为画面匹配可使用的素材与资源。" },
  { id: "storyboard", name: "编排分镜", description: "将讲稿与画面编排为分镜，产出后可在下方逐一查看。" },
  { id: "generation", name: "生成场景", description: "根据分镜制作动画场景，准备进入渲染。" },
  { id: "rendering", name: "视频制作", description: "协调配音、动画渲染与视频合成；子任务可能并行进行。" },
  { id: "narration", name: "生成配音", description: "生成真实配音与时间信息，为画面和字幕提供同步依据。", child: true },
  { id: "animation", name: "动画渲染", description: "将动画场景渲染成画面，已完成的片段可在下方查看。", child: true },
  { id: "composition", name: "最终合成", description: "同步画面、配音与字幕，输出可播放、可下载的最终视频。", child: true },
];
const phaseById = new Map(phases.map((phase) => [phase.id, phase]));
const numberFormat = new Intl.NumberFormat("zh-CN");
const tokenLabel = (value: number | null | undefined) => isRecordedNumber(value) ? numberFormat.format(value) : "未返回";
type PhaseState = StageTelemetry["status"] | "pending" | "unrecorded";
const stateLabels: Record<PhaseState, string> = {
  running: "进行中", completed: "已完成", failed: "未完成", cached: "已复用", interrupted: "已中断", pending: "待开始", unrecorded: "未记录",
};

function durationLabel(value: number | null | undefined) {
  if (!isRecordedNumber(value)) return "未记录";
  const seconds = Math.floor(value / 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  if (hours) return `${hours}小时${minutes}分${rest}秒`;
  return minutes ? `${minutes}分${rest}秒` : `${rest}秒`;
}

function useSnapshotDelta(job: Job, synchronized: boolean) {
  const [now, setNow] = useState(() => performance.now());
  const active = synchronized && job.status === "running" && Boolean(job.telemetry?.running);
  useEffect(() => {
    setNow(performance.now());
    if (!active) return;
    const timer = window.setInterval(() => setNow(performance.now()), 1000);
    return () => window.clearInterval(timer);
  }, [job.id, job.telemetryReceivedAt, active]);
  return active && job.telemetry?.as_of && isRecordedNumber(job.telemetryReceivedAt)
    ? Math.min(30000, Math.max(0, now - job.telemetryReceivedAt)) : 0;
}

function elapsed(stage: StageTelemetry | undefined, delta: number, active: boolean) {
  return isRecordedNumber(stage?.elapsed_ms) ? stage.elapsed_ms + (active ? delta : 0) : null;
}

function Disclosure({ id, open, children }: { id: string; open: boolean; children: ReactNode }) {
  return (
    <div className="task-disclosure" id={id} data-open={open} aria-hidden={!open} inert={!open}>
      <div className="task-disclosure-inner">{children}</div>
    </div>
  );
}

function StateIcon({ state }: { state: PhaseState }) {
  if (state === "completed" || state === "cached") return <Check size={15} />;
  if (state === "failed") return <CircleAlert size={15} />;
  if (state === "interrupted") return <Pause size={14} />;
  if (state === "running") return <span className="task-active-dot" />;
  return <Circle size={13} />;
}

function usageCost(usage: TokenUsage | undefined, state: PhaseState) {
  const estimate = estimateTextCost(usage);
  if (estimate) return costLabel(estimate);
  if (!usage) return state === "pending" ? "待开始" : "未记录";
  if (usage.calls === 0 && state !== "running") return "—";
  return "待返回";
}

function StageCard({ phase, job, delta, synchronized }: { phase: Phase; job: Job; delta: number; synchronized: boolean }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const stage = job.telemetry?.stages[phase.id];
  const terminal = job.status === "succeeded" || job.status === "failed" || job.status === "cancelled";
  const recordedState = stage?.status;
  const state: PhaseState = job.status === "cancelled" && recordedState === "running" ? "interrupted"
    : recordedState ?? (job.telemetry?.timing_recorded && !terminal ? "pending" : "unrecorded");
  const active = synchronized && job.status === "running" && Boolean(job.telemetry?.running) && state === "running";
  const estimate = estimateTextCost(stage);
  return (
    <article className="task-stage" data-state={state} data-child={Boolean(phase.child)}>
      <button className="task-stage-button" type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        <span className="task-stage-icon" aria-hidden="true"><StateIcon state={state === "running" && !synchronized ? "interrupted" : state} /></span>
        <span className="task-stage-copy">
          <strong>{phase.name}</strong>
          <span className="task-stage-status">{state === "running" && !synchronized ? "状态待同步" : stateLabels[state]}</span>
        </span>
        <span className="task-stage-metrics">
          <span data-metric="input"><small>输入词元</small><strong>{state === "pending" ? "—" : tokenLabel(stage?.input_tokens)}</strong></span>
          <span data-metric="output"><small>输出词元</small><strong>{state === "pending" ? "—" : tokenLabel(stage?.output_tokens)}</strong></span>
          <span data-metric="cost"><small>估算金额{estimate?.partial ? " · 已知部分" : ""}</small><strong>{usageCost(stage, state)}</strong></span>
          <span data-metric="duration"><small>实际耗时</small><strong>{state === "pending" ? "—" : durationLabel(elapsed(stage, delta, active))}</strong></span>
        </span>
        <ChevronDown size={16} className="task-chevron" data-open={open} aria-hidden="true" />
      </button>
      <Disclosure id={id} open={open}>
        <div className="task-stage-detail">
          <p className="task-stage-description">{phase.description}</p>
          {stage ? (
            <>
              <dl className="task-detail-grid">
                <div><dt>缓存输入</dt><dd>{tokenLabel(stage.cached_input_tokens)}</dd></div>
                <div><dt>推理词元</dt><dd>{tokenLabel(stage.reasoning_tokens)}</dd></div>
                <div><dt>已结束调用</dt><dd>{numberFormat.format(stage.calls)}</dd></div>
                <div><dt>执行记录</dt><dd>{numberFormat.format(stage.attempts)} 次</dd></div>
              </dl>
              <p className="task-detail-note">
                {stage.calls === 0 ? "尚未记录此阶段的文本模型调用。" : "词元来自模型实际返回；缓存与推理用量已包含在输入、输出中，不重复计费。"}
                {stage.unreported_calls > 0 && ` ${stage.unreported_calls} 次调用未返回完整用量，金额仅覆盖已知部分。`}
                {estimate?.cacheIncomplete && " 缓存细分未完整确认，估算仅扣除已确认的缓存优惠。"}
                {stage.cached_runs > 0 && ` 已复用 ${stage.cached_runs} 次缓存结果。`}
              </p>
            </>
          ) : <p className="task-detail-note">{state === "pending" ? "此阶段尚未开始，耗时与用量将在执行后显示。" : "此记录没有该阶段的耗时与用量数据。"}</p>}
        </div>
      </Disclosure>
    </article>
  );
}

export function TaskProgress({ job, synchronized = true }: { job: Job; synchronized?: boolean }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const delta = useSnapshotDelta(job, synchronized);
  const records = job.telemetry?.stages ?? {};
  const running = job.status === "running";
  const waiting = job.status === "queued";
  const succeeded = job.status === "succeeded";
  const failed = job.status === "failed";
  const cancelling = job.status === "cancelling";
  const cancelled = job.status === "cancelled";
  const activeIds = running ? Object.keys(records).filter((key) => records[key].status === "running") : [];
  const activeChildren = activeIds.filter((key) => phaseById.get(key)?.child);
  const candidates = activeChildren.length ? activeChildren : activeIds;
  // When the umbrella rendering stage runs alongside a child, show the actual
  // current activity; never infer completion of earlier tasks from its order.
  const activeId = [...candidates].sort((a, b) =>
    (records[b].started_at ?? "").localeCompare(records[a].started_at ?? ""),
  )[0];
  const failedId = Object.keys(records).filter((key) => records[key].status === "failed").sort((a, b) => (records[b].completed_at ?? "").localeCompare(records[a].completed_at ?? ""))[0];
  const currentId = failed ? (phaseById.has(job.stage) ? job.stage : failedId ?? job.stage) : activeId ?? job.stage;
  const phase = phaseById.get(currentId);
  const currentName = phase?.name ?? stageLabels[currentId] ?? "处理任务";
  const completed = Object.values(records).filter((stage) => stage.status === "completed" || stage.status === "cached").length;
  const otherActive = candidates.filter((key) => key !== currentId).map((key) => phaseById.get(key)?.name ?? "其他任务");
  const title = succeeded ? "视频已完成" : cancelled ? "制作已停止" : cancelling ? "正在停止制作" : failed ? "制作暂时中断" : waiting ? "等待开始制作" : currentName;
  const description = !synchronized && (running || waiting) ? "连接暂时中断，正在显示最近一次制作进度。" : succeeded ? "成片已就绪，可以观看与下载。"
    : cancelled ? "制作已结束，已保留完成的内容和实际用量。"
    : cancelling ? "正在结束制作工作，完全停止后即可创建新视频。"
    : failed ? `${currentName}未完成，已保留现有产物。`
    : waiting ? "任务已加入队列，开始后会自动更新。"
    : otherActive.length ? `同时进行：${otherActive.join("、")}`
    : phase?.description ?? "正在处理当前任务，进展会自动更新。";
  const telemetry = job.telemetry;
  const estimate = estimateTextCost(telemetry?.usage);
  // Job totals already merge parallel execution intervals and count each
  // model call once. Adding stage totals would double-count nested work.
  const totalElapsed = telemetry?.timing_recorded && isRecordedNumber(telemetry.elapsed_ms)
    ? telemetry.elapsed_ms + (running && telemetry.running ? delta : 0)
    : null;
  const allPhases = [...phases, ...Object.keys(records).filter((key) => !phaseById.has(key)).map((key, index) => ({
    id: key, name: stageLabels[key] ?? `其他任务 ${index + 1}`, description: "此任务的实际耗时与模型用量记录。",
  }))];

  useEffect(() => setOpen(false), [job.id]);

  return (
    <section className="task-progress task-progress-inline" data-status={job.status} aria-label="视频制作进度">
      <button className="task-current-button" type="button" aria-expanded={open} aria-controls={id} title={description} onClick={() => setOpen(!open)}>
        <span className="task-current-mark" aria-hidden="true">
          {running || waiting ? <BrandMark animated={synchronized} /> : succeeded ? <Check size={23} /> : cancelling || cancelled ? <Square size={22} /> : <CircleAlert size={23} />}
        </span>
        <span className="task-current-copy">
          <strong key={title} className="task-current-title" aria-live="polite">
            {title}{!synchronized && (running || waiting) && " · 状态待同步"}
          </strong>
        </span>
        <ChevronDown size={17} className="task-chevron" data-open={open} aria-hidden="true" />
      </button>
      <Disclosure id={id} open={open}>
        <div className="task-expanded-header">
          <div className="task-expanded-label">
            <h3>制作详情</h3>
            <small>{completed} 项已完成</small>
          </div>
          <div className="task-total-summary">
            <span className="task-total-metric" title="全部文本模型调用按谷价折算，不含配音、素材和渲染费用">
              <small>估算总额{estimate?.partial ? " · 已知部分" : ""}</small>
              <strong>{estimate ? costLabel(estimate) : telemetry?.usage ? "待返回" : "未记录"}</strong>
            </span>
            <span className="task-total-metric" title="整个任务累计执行时间，不含排队和中断等待">
              <small>累计耗时</small>
              <strong>{durationLabel(totalElapsed)}</strong>
            </span>
          </div>
        </div>
        <div className="task-stages">
          {allPhases.map((item) => <StageCard key={`${job.id}-${item.id}`} phase={item} job={job} delta={delta} synchronized={synchronized} />)}
        </div>
      </Disclosure>
    </section>
  );
}
