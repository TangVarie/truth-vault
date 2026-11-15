import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Fraunces, Hanken_Grotesk } from "next/font/google";
import "./globals.css";

/** 编辑级显示衬线(Bone & Ink 世界的大标题 + 巨号数字)。 */
const fraunces = Fraunces({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-fraunces",
});
/** 暖灰正文 grotesque(编辑级正文/UI)。 */
const hanken = Hanken_Grotesk({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-hanken",
});

/**
 * 全站不让搜索引擎收录(含公开首页、对外看板和 Vercel 预览域名)：这里的 robots 落到每一条路由的
 * <meta name="robots">，另有 app/robots.ts(robots.txt 全站 Disallow)和 next.config.mjs 里的
 * X-Robots-Tag 响应头，三处说的是同一件事。子页面自己写 metadata 时不要把 robots 改回可收录。
 */
export const metadata: Metadata = {
  robots: { index: false, follow: false, googleBot: { index: false, follow: false } },
  title: "BYWOOD 芭梧 · AI 驱动的内容增长中台",
  description:
    "把每一次投放,变成越投越准的策略复利 —— 一套结构化飞轮,照见从投放到决策到复利的每一环。",
  openGraph: {
    title: "BYWOOD 芭梧 · AI 驱动的内容增长中台",
    description: "把每一次投放,变成越投越准的策略复利。结构化策略库 · 数据飞轮 · 越用越强。",
    type: "website",
    locale: "zh_CN",
    siteName: "BYWOOD 芭梧",
  },
  twitter: {
    card: "summary_large_image",
    title: "BYWOOD 芭梧 · AI 驱动的内容增长中台",
    description: "把每一次投放,变成越投越准的策略复利。",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="zh-CN"
      className={`${GeistSans.variable} ${GeistMono.variable} ${fraunces.variable} ${hanken.variable}`}
    >
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
