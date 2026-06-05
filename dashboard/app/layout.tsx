import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "飞轮总看板 · Flywheel Dashboard",
  description: "帆谷飞轮生态(Truth Vault / autowriter / sanshengliubu)实时态势",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
