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

export const metadata: Metadata = {
  title: "BYWOOD 芭梧 · ROC 增长智能中台",
  description:
    "把策略变成越用越准的增长复利 —— 一套结构化飞轮,照见从投放到决策到复利的每一环。",
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
