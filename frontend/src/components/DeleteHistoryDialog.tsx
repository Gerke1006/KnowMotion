import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Trash2 } from "lucide-react";
import type { Job } from "../studio";

export function DeleteHistoryDialog({ job, onClose, onDelete }: {
  job: Job;
  onClose: () => void;
  onDelete: (job: Job) => Promise<void>;
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
      if (previous?.isConnected && getComputedStyle(previous).visibility !== "hidden") previous.focus();
      else document.getElementById("main-content")?.focus();
    };
  }, []);

  async function confirm() {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await onDelete(job);
    } catch (problem) {
      if (mounted.current) setError(problem instanceof Error ? problem.message : "删除失败，请稍后重试。");
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <dialog ref={dialog} className="history-delete-dialog" aria-labelledby="delete-history-title"
      aria-describedby="delete-history-description" aria-busy={busy}
      onKeyDown={(event) => { if (event.key === "Escape" || event.key === "Tab") event.stopPropagation(); }}
      onCancel={(event) => { event.preventDefault(); if (!pending.current) onClose(); }}>
      <span className="delete-dialog-icon"><Trash2 size={23} strokeWidth={1.6} /></span>
      <h2 id="delete-history-title">删除这条记录？</h2>
      <p id="delete-history-description">这条记录及对应视频将从工作台移除，本地生成文件会保留。</p>
      <blockquote className="delete-record-title">{job.topic}</blockquote>
      {error && <p className="delete-dialog-error" role="alert">{error}</p>}
      <div className="delete-dialog-actions">
        <button className="button-secondary" autoFocus disabled={busy} onClick={onClose}>取消</button>
        <button className="button-danger" disabled={busy} onClick={() => void confirm()}>
          {busy ? <LoaderCircle size={15} className="spin" /> : <Trash2 size={15} />}
          {busy ? "正在删除" : "删除记录"}
        </button>
      </div>
    </dialog>
  );
}
