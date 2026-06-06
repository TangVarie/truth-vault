import { cnNum, comma } from "@/config/showcase";

/**
 * 数字渲染:**SSR 直出真实值**(消灭 "0" 闪屏 —— 微信/飞书 WebView、截图、低端机首屏要真值),
 * hydrate 后只做一次极轻淡入上移(.num-in),不再"从 0 数到目标值"的演示噱头(P0)。
 * 保留 duration 形参仅为兼容旧调用,已不使用。
 */
export default function CountUp({
  value,
  format = "comma",
}: {
  value: number;
  duration?: number;
  format?: "cn" | "comma";
}) {
  const fmt = format === "cn" ? cnNum : comma;
  return <span className="tabular-nums num-in">{fmt(value)}</span>;
}
