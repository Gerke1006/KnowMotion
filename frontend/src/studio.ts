export type Job = {
  id: string;
  topic: string;
  mode: string;
  status: "queued" | "running" | "succeeded" | "failed";
  stage: string;
  progress: number;
  error: string | null;
  created_at: string;
  updated_at: string;
  artifacts: Record<string, string>;
};

export type StudioRoute = { view: "new" | "library" | "history"; id?: string };
export function readRoute(): StudioRoute {
  const query = new URLSearchParams(location.search);
  const id = query.get("job");
  if (id) return { view: "history", id };
  const view = query.get("view");
  return { view: view === "library" || view === "history" ? view : "new" };
}
export const statusLabels = {
  queued: "排队中",
  running: "制作中",
  succeeded: "已完成",
  failed: "未完成",
};
export const stageLabels: Record<string, string> = {
  queued: "正在等待开始",
  resuming: "正在恢复任务",
  identify: "理解主题",
  research: "检索与研究",
  teaching: "生成讲稿",
  visual: "规划画面",
  assets: "匹配素材",
  storyboard: "编排分镜",
  generation: "生成动画场景",
  rendering: "配音、渲染与合成",
  complete: "视频已就绪",
};
export const stages = [
  { keys: ["identify"], name: "理解主题", detail: "识别学科，明确讲解目标" },
  {
    keys: ["research"],
    name: "研究知识",
    detail: "检索真实资料，整理核心概念",
  },
  { keys: ["teaching"], name: "编写讲稿", detail: "组织讲解顺序，生成旁白" },
  {
    keys: ["visual", "assets", "storyboard"],
    name: "设计分镜",
    detail: "规划画面与动画，匹配素材",
  },
  {
    keys: ["generation"],
    name: "生成场景",
    detail: "将分镜转化为可渲染的场景",
  },
  { keys: ["rendering"], name: "合成视频", detail: "生成配音，同步字幕与画面" },
];
export const timeLabel = (value: string) =>
  new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
export const durationLabel = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
export function getDraft() {
  try {
    return localStorage.getItem("knowmotion.prompt") || "";
  } catch {
    return "";
  }
}
export function saveDraft(value: string) {
  try {
    localStorage.setItem("knowmotion.prompt", value);
  } catch {
    /* Storage is optional. */
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api(
  path: string,
  token: string,
  init: RequestInit = {},
  timeoutMs = 20000,
) {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const timeout = AbortSignal.timeout(timeoutMs);
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers,
      signal: init.signal ? AbortSignal.any([init.signal, timeout]) : timeout,
    });
  } catch (error) {
    if (init.signal?.aborted) throw error;
    throw new Error("暂时无法连接服务，请稍后重试。");
  }
  if (!response.ok) {
    const messages: Record<number, string> = {
      401: "服务需要访问令牌，请在右上角自定义 API 中连接。",
      404: "没有找到这个任务。",
      409: "任务状态已更新，请刷新后重试。",
      422: "请检查输入内容，知识点最多 300 字。",
      429: "当前任务较多，请稍后再试。",
    };
    throw new ApiError(
      messages[response.status] || "服务暂时不可用，请稍后重试。",
      response.status,
    );
  }
  return response;
}
