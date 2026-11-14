import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Square } from "lucide-react";
import type { Job } from "../studio";

export function CancelJobDialog({ job, shared, onClose, onStop }: {
  job: Job;
  shared: boolean;
  onClose: () => void;
  onStop: (job: Job) => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const pending = useRef(false);
  const mounted = useRef(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    mounted.current = true;
    const previous = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    return () => {
      mounted.current = false;
      dialog.current?.close();
      if (previous?.isConnected && !previous.hasAttribute("disabled")) previous.focus();
      else document.getElementById("main-content")?.focus();
    };
  }, []);

  async function confirm() {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await onStop(job);
    } catch (problem) {
      if (mounted.current) setError(problem instanceof Error ? problem.message : "停止请求未确认，请重试。");
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <dialog ref={dialog} className="history-delete-dialog stop-job-dialog" aria-labelledby="stop-job-title"
      aria-describedby="stop-job-description" aria-busy={busy}
      onKeyDown={(event) => { if (event.key === "Escape" || event.key === "Tab") event.stopPropagation(); }}
      onCancel={(event) => { event.preventDefault(); if (!pending.current) onClose(); }}>
      <span className="delete-dialog-icon"><Square size={21} strokeWidth={1.6} /></span>
      <h2 id="stop-job-title">停止这次视频制作？</h2>
      <p id="stop-job-description">{shared ? "这是所有人共享的任务，停止后所有访客都会看到“已停止”。" : "停止后，这次任务将结束。"}
        已完成的内容会保留，当前草稿不会丢失。等制作完全停止后，即可生成你自己的视频。</p>
      <blockquote className="delete-record-title">{job.topic}</blockquote>
      {error && <p className="delete-dialog-error" role="alert">{error}</p>}
      <div className="delete-dialog-actions">
        <button className="button-secondary" autoFocus disabled={busy} onClick={onClose}>继续等待</button>
        <button className="button-danger" disabled={busy} onClick={() => void confirm()}>
          {busy ? <LoaderCircle size={15} className="spin" /> : <Square size={15} />}
          {busy ? "正在请求停止" : "停止制作"}
        </button>
      </div>
    </dialog>
  );
}
