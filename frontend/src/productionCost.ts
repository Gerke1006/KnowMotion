import type { TokenUsage } from "./studio";

// A reference estimate requested by the user, never a provider invoice.
// Rates are CNY per million tokens, verified against the official price sheet.
export const FLASH_OFF_PEAK_PRICING = {
  model: "deepseek-flash",
  input: 1,
  cachedInput: 0.02,
  output: 4,
  checkedAt: "2026-11-14",
  source: "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
} as const;

export type CostEstimate = {
  lower: number;
  upper: number;
  partial: boolean;
  cacheIncomplete: boolean;
};

export const isRecordedNumber = (value: number | null | undefined): value is number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0;

export function estimateTextCost(usage?: TokenUsage): CostEstimate | null {
  if (!usage || !isRecordedNumber(usage.input_tokens) || !isRecordedNumber(usage.output_tokens)) return null;
  const input = usage.input_tokens;
  const output = usage.output_tokens;
  const cache = usage.cached_input_tokens;
  if (isRecordedNumber(cache) && cache > input) return null;

  // The current telemetry sums available cache details without reporting how
  // many calls supplied them. For multiple calls, that sum is only a lower
  // bound on the cached tokens. Preserve the uncertainty as an amount range.
  const cacheComplete = input === 0 || (usage.calls === 1 && isRecordedNumber(cache)) || cache === input;
  const minimumCached = isRecordedNumber(cache) ? cache : 0;
  const maximumCached = cacheComplete ? minimumCached : input;
  const cost = (cached: number) => (
    (input - cached) * FLASH_OFF_PEAK_PRICING.input +
    cached * FLASH_OFF_PEAK_PRICING.cachedInput +
    output * FLASH_OFF_PEAK_PRICING.output
  ) / 1_000_000;

  return {
    lower: cost(maximumCached),
    upper: cost(minimumCached),
    partial: usage.unreported_calls > 0,
    cacheIncomplete: !cacheComplete,
  };
}

const amountFormat = new Intl.NumberFormat("zh-CN", {
  minimumFractionDigits: 3,
  maximumFractionDigits: 3,
  useGrouping: false,
});

export function costLabel(estimate: CostEstimate | null): string {
  if (!estimate) return "待返回";
  // Display one conservative reference amount, applying discounts only to
  // confirmed cached input. Missing usage remains unknown, never a billed zero.
  return `¥${amountFormat.format(estimate.upper)}`;
}
