import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import {
  ChevronDown,
  KeyRound,
  LoaderCircle,
  RotateCcw,
  X,
} from "lucide-react";

type ApiConfiguration = {
  model_base_url: string;
  model_name: string;
  model_key_configured: boolean;
  minimax_base_url: string;
  minimax_model: string;
  minimax_voice_id: string;
  minimax_key_configured: boolean;
  customized: boolean;
  execution_backend: string;
  editable?: boolean;
};

type ConfigurationForm = {
  model_base_url: string;
  model_name: string;
  model_api_key: string;
  minimax_base_url: string;
  minimax_model: string;
  minimax_voice_id: string;
  minimax_api_key: string;
};

type ApiSettingsProps = {
  open: boolean;
  onClose: () => void;
  token: string;
  onTokenChange: (value: string) => void;
  onSaved: () => void;
};

const emptyForm: ConfigurationForm = {
  model_base_url: "",
  model_name: "",
  model_api_key: "",
  minimax_base_url: "",
  minimax_model: "",
  minimax_voice_id: "",
  minimax_api_key: "",
};

class ConfigurationError extends Error {
  constructor(public status: number) {
    super(
      {
        401: "访问令牌无效，请输入服务端配置的访问令牌。",
        409: "当前执行后端暂不支持在页面修改接口，请在服务端配置。",
        422: "请检查服务地址和模型名称。地址应为接口基址，不包含具体请求路径。",
        429: "请求过于频繁，请稍后重试。",
      }[status] || "服务暂时不可用，请稍后重试。",
    );
  }
}

async function requestConfiguration(
  token: string,
  signal: AbortSignal,
  init: RequestInit = {},
): Promise<ApiConfiguration> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch("/settings/api", {
    ...init,
    headers,
    signal: AbortSignal.any([signal, AbortSignal.timeout(20000)]),
    cache: "no-store",
  });
  // Do not surface raw provider/request error bodies, which can contain secrets.
  if (!response.ok) throw new ConfigurationError(response.status);
  return response.json();
}

export function ApiSettings({
  open,
  onClose,
  token,
  onTokenChange,
  onSaved,
}: ApiSettingsProps) {
  const ids = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const mutationRef = useRef<AbortController | null>(null);
  const busyRef = useRef(false);
  const [config, setConfig] = useState<ApiConfiguration | null>(null);
  const [form, setForm] = useState<ConfigurationForm>(emptyForm);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<"save" | "reset" | null>(null);
  const [error, setError] = useState("");
  const [needsToken, setNeedsToken] = useState(false);
  const [tokenInput, setTokenInput] = useState("");
  const [confirmReset, setConfirmReset] = useState(false);
  const [reload, setReload] = useState(0);
  const editable = config?.editable !== false;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (open && dialog && !dialog.open) dialog.showModal();
    if (!open) {
      dialog?.close();
      mutationRef.current?.abort();
      mutationRef.current = null;
      busyRef.current = false;
      setBusy(null);
      setTokenInput("");
      setForm(emptyForm);
      setConfirmReset(false);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoading(true);
    setConfig(null);
    setError("");
    setNeedsToken(false);
    void requestConfiguration(token, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setConfig(data);
        setForm({
          model_base_url: data.model_base_url,
          model_name: data.model_name,
          model_api_key: "",
          minimax_base_url: data.minimax_base_url,
          minimax_model: data.minimax_model,
          minimax_voice_id: data.minimax_voice_id,
          minimax_api_key: "",
        });
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        if (reason instanceof ConfigurationError) {
          setNeedsToken(reason.status === 401);
          setError(reason.message);
        } else {
          setError("暂时无法读取接口配置，请检查连接后重试。");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [open, token, reload]);

  useEffect(() => () => mutationRef.current?.abort(), []);

  function update(field: keyof ConfigurationForm, value: string) {
    setForm((previous) => ({ ...previous, [field]: value }));
    setConfirmReset(false);
  }

  function close() {
    if (busyRef.current) return;
    setTokenInput("");
    setForm((previous) => ({
      ...previous,
      model_api_key: "",
      minimax_api_key: "",
    }));
    onClose();
  }

  function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextToken = tokenInput.trim();
    if (!nextToken) return;
    onTokenChange(nextToken);
    setTokenInput("");
    setReload((previous) => previous + 1);
  }

  async function mutate(action: "save" | "reset") {
    if (busyRef.current || !config || !editable) return;
    if (action === "save") {
      const validUrl = (value: string) => {
        try {
          const url = new URL(value);
          return ["http:", "https:"].includes(url.protocol);
        } catch {
          return false;
        }
      };
      if (
        !validUrl(form.model_base_url.trim()) ||
        !validUrl(form.minimax_base_url.trim()) ||
        !form.model_name.trim() ||
        !form.minimax_model.trim() ||
        !form.minimax_voice_id.trim()
      ) {
        setError("请填写有效的网络服务地址、模型名称和音色标识。");
        return;
      }
    }
    const controller = new AbortController();
    mutationRef.current = controller;
    busyRef.current = true;
    setBusy(action);
    setError("");
    try {
      const payload = Object.fromEntries(
        Object.entries(form).map(([key, value]) => [key, value.trim()]),
      );
      await requestConfiguration(token, controller.signal, {
        method: action === "save" ? "PUT" : "DELETE",
        ...(action === "save" && { body: JSON.stringify(payload) }),
      });
      if (controller.signal.aborted) return;
      setForm(emptyForm);
      setTokenInput("");
      setConfirmReset(false);
      onSaved();
      onClose();
    } catch (reason) {
      if (controller.signal.aborted) return;
      if (reason instanceof ConfigurationError) {
        setError(reason.message);
        if (reason.status === 401) {
          setNeedsToken(true);
          setForm((previous) => ({
            ...previous,
            model_api_key: "",
            minimax_api_key: "",
          }));
        }
      } else {
        setError("保存结果暂时无法确认，请关闭并重新打开设置后核对。");
      }
    } finally {
      if (mutationRef.current === controller) {
        busyRef.current = false;
        mutationRef.current = null;
        setBusy(null);
      }
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="api-dialog"
      aria-labelledby={`${ids}-title`}
      aria-describedby={`${ids}-description`}
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
    >
      <div className="modal-heading">
        <span className="modal-symbol" aria-hidden="true">
          <KeyRound size={19} />
        </span>
        <div>
          <h2 id={`${ids}-title`}>自定义接口</h2>
          <p id={`${ids}-description`}>
            连接你的模型服务，生成自己的知识视频。
          </p>
        </div>
        <button
          className="modal-close"
          type="button"
          aria-label="关闭接口设置"
          disabled={!!busy}
          onClick={close}
        >
          <X size={19} />
        </button>
      </div>

      {error && (
        <p className="config-message is-error" role="alert">
          {error}
        </p>
      )}

      {loading ? (
        <div className="config-loading" role="status">
          <LoaderCircle className="spin" size={18} />
          正在读取配置…
        </div>
      ) : needsToken ? (
        <form onSubmit={connect} className="config-access-form">
          <div className="form-field">
            <label htmlFor={`${ids}-access`}>服务访问令牌</label>
            <input
              id={`${ids}-access`}
              className="field-input"
              type="password"
              autoFocus
              autoComplete="off"
              value={tokenInput}
              required
              onChange={(event) => setTokenInput(event.target.value)}
              aria-describedby={`${ids}-access-help`}
            />
            <p className="form-help" id={`${ids}-access-help`}>
              这是本工作台服务的访问令牌，不是模型接口密钥。仅在当前页面会话中使用。
            </p>
          </div>
          <div className="modal-actions">
            <button type="button" className="button-secondary" onClick={close}>
              取消
            </button>
            <button
              className="button-primary"
              type="submit"
              disabled={!tokenInput.trim()}
            >
              连接服务
            </button>
          </div>
        </form>
      ) : config ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void mutate("save");
          }}
        >
          {!editable && (
            <p className="config-message" role="status">
              当前执行后端不支持在页面修改配置，请在服务端统一配置模型接口。
            </p>
          )}
          <fieldset
            disabled={!!busy || !editable}
            className="config-fields"
            onInvalid={(event) => {
              const section = event.target instanceof HTMLElement ? event.target.closest("details") : null;
              if (section) section.open = true;
            }}
          >
            <div className="config-section-title">
              <h3>文本模型</h3>
              <span>{config.customized ? "自定义配置" : "项目默认配置"}</span>
            </div>
            <div className="form-field">
              <label htmlFor={`${ids}-model-url`}>服务地址</label>
              <input
                id={`${ids}-model-url`}
                className="field-input"
                type="url"
                autoFocus
                autoComplete="off"
                value={form.model_base_url}
                required
                placeholder="输入服务商提供的接口基址"
                onChange={(event) =>
                  update("model_base_url", event.target.value)
                }
                aria-describedby={`${ids}-url-help`}
              />
              <p className="form-help" id={`${ids}-url-help`}>
                支持兼容对话补全的接口，填写服务基址即可。
              </p>
            </div>
            <div className="form-field">
              <label htmlFor={`${ids}-model`}>模型名称</label>
              <input
                id={`${ids}-model`}
                className="field-input"
                type="text"
                autoComplete="off"
                value={form.model_name}
                required
                placeholder="输入服务商提供的模型名称"
                onChange={(event) => update("model_name", event.target.value)}
              />
            </div>
            <div className="form-field">
              <label htmlFor={`${ids}-model-key`}>
                接口密钥{" "}
                {config.model_key_configured && (
                  <span className="key-state">已配置</span>
                )}
              </label>
              <input
                id={`${ids}-model-key`}
                className="field-input"
                type="password"
                autoComplete="new-password"
                value={form.model_api_key}
                placeholder={
                  config.model_key_configured
                    ? "已配置，留空保留现有密钥"
                    : "输入文本模型接口密钥"
                }
                onChange={(event) =>
                  update("model_api_key", event.target.value)
                }
                aria-describedby={`${ids}-key-help`}
              />
              <p className="form-help" id={`${ids}-key-help`}>
                密钥保存在本地服务配置中，不会写入视频或任务记录。
              </p>
            </div>

            <details className="config-section">
              <summary>
                语音合成服务
                <ChevronDown size={16} aria-hidden="true" />
              </summary>
              <p className="form-help">
                沿用当前配音配置即可，文本与配音使用各自的接口密钥。
              </p>
              <div className="form-field">
                <label htmlFor={`${ids}-voice-url`}>服务地址</label>
                <input
                  id={`${ids}-voice-url`}
                  className="field-input"
                  type="url"
                  autoComplete="off"
                  value={form.minimax_base_url}
                  required
                  onChange={(event) =>
                    update("minimax_base_url", event.target.value)
                  }
                />
              </div>
              <div className="form-grid">
                <div className="form-field">
                  <label htmlFor={`${ids}-voice-model`}>配音模型</label>
                  <input
                    id={`${ids}-voice-model`}
                    className="field-input"
                    type="text"
                    autoComplete="off"
                    value={form.minimax_model}
                    required
                    onChange={(event) =>
                      update("minimax_model", event.target.value)
                    }
                  />
                </div>
                <div className="form-field">
                  <label htmlFor={`${ids}-voice-id`}>音色标识</label>
                  <input
                    id={`${ids}-voice-id`}
                    className="field-input"
                    type="text"
                    autoComplete="off"
                    value={form.minimax_voice_id}
                    required
                    onChange={(event) =>
                      update("minimax_voice_id", event.target.value)
                    }
                  />
                </div>
              </div>
              <div className="form-field">
                <label htmlFor={`${ids}-voice-key`}>
                  接口密钥{" "}
                  {config.minimax_key_configured && (
                    <span className="key-state">已配置</span>
                  )}
                </label>
                <input
                  id={`${ids}-voice-key`}
                  className="field-input"
                  type="password"
                  autoComplete="new-password"
                  value={form.minimax_api_key}
                  placeholder={
                    config.minimax_key_configured
                      ? "已配置，留空保留现有密钥"
                      : "输入语音合成服务接口密钥"
                  }
                  onChange={(event) =>
                    update("minimax_api_key", event.target.value)
                  }
                />
              </div>
            </details>
          </fieldset>

          <p className="form-help config-scope">
            保存后用于接下来开始制作的任务，正在制作的视频不受影响。
          </p>

          {confirmReset && (
            <div
              className="config-reset-confirm"
              role="group"
              aria-label="确认恢复默认配置"
            >
              <p>恢复项目启动时的默认接口配置？当前自定义配置将被移除。</p>
              <div>
                <button
                  className="button-quiet"
                  type="button"
                  disabled={!!busy}
                  onClick={() => setConfirmReset(false)}
                >
                  取消
                </button>
                <button
                  className="button-secondary"
                  type="button"
                  disabled={!!busy}
                  onClick={() => void mutate("reset")}
                >
                  {busy === "reset" ? (
                    <LoaderCircle size={15} className="spin" />
                  ) : (
                    <RotateCcw size={15} />
                  )}
                  确认恢复
                </button>
              </div>
            </div>
          )}
          <div className="modal-actions">
            {config.customized && editable && !confirmReset && (
              <button
                className="button-quiet reset-settings"
                type="button"
                disabled={!!busy}
                onClick={() => setConfirmReset(true)}
              >
                恢复默认
              </button>
            )}
            <button
              className="button-secondary"
              type="button"
              onClick={close}
              disabled={!!busy}
            >
              取消
            </button>
            <button
              className="button-primary"
              type="submit"
              disabled={!!busy || !editable}
            >
              {busy === "save" && <LoaderCircle size={15} className="spin" />}
              {busy === "save" ? "正在保存…" : "保存配置"}
            </button>
          </div>
        </form>
      ) : (
        <div className="modal-actions">
          <button className="button-secondary" type="button" onClick={close}>
            关闭
          </button>
          <button
            className="button-primary"
            type="button"
            onClick={() => setReload((previous) => previous + 1)}
          >
            重新读取
          </button>
        </div>
      )}
    </dialog>
  );
}

export default ApiSettings;
