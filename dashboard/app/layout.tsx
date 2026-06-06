import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";

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
    <html lang="zh-CN" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
