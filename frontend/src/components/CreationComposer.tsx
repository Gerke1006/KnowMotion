import type { ReactNode, RefObject } from "react";
import { ArrowUpRight, Film, LoaderCircle } from "lucide-react";

export function CreationComposer({ prompt, onPromptChange, onSubmit, submitting, textareaRef, error, disabled = false, disabledLabel }: {
  prompt: string;
  onPromptChange: (value: string) => void;
  onSubmit: () => void;
  submitting: boolean;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  error?: ReactNode;
  disabled?: boolean;
  disabledLabel?: string;
}) {
  return (
    <div className="workspace-composer-dock">
      <form className="create-form composer-form" onSubmit={(event) => { event.preventDefault(); if (!disabled && !submitting) onSubmit(); }}>
        <label className="composer-label" htmlFor="knowledge-prompt">创作描述</label>
        <div className="prompt-editor">
          <textarea ref={textareaRef} id="knowledge-prompt" value={prompt} maxLength={300} disabled={submitting}
            placeholder="输入你想讲解的知识点，描述你想让它如何动起来…"
            onChange={(event) => onPromptChange(event.target.value)}
            onKeyDown={(event) => {
              if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !event.nativeEvent.isComposing) {
                event.preventDefault();
                if (!disabled && !submitting) onSubmit();
              }
            }} />
        </div>
        {error}
        <div className="generate-toolbar">
          <span className="composer-kind"><Film size={16} strokeWidth={1.6} />知识动画</span>
          <span className="keyboard-hint"><kbd>控制键</kbd><span>+</span><kbd>回车键</kbd><span>生成</span></span>
          <span className="character-count">{prompt.length}<span> / 300</span></span>
          <button className="button-primary generate-button" type="submit" disabled={!prompt.trim() || submitting || disabled}>
            {submitting ? <><LoaderCircle size={17} className="spin" />正在创建</> : disabled ? <>{disabledLabel || "暂不可生成"}</> : <>生成视频<ArrowUpRight size={18} /></>}
          </button>
        </div>
      </form>
    </div>
  );
}
