import type { MetadataRoute } from "next";

/**
 * /robots.txt：全站不许抓取。和 app/layout.tsx 的 robots 元信息、next.config.mjs 的 X-Robots-Tag
 * 响应头是同一个决定的三处落点(看板是给客户当面看的，不进搜索结果；Vercel 预览域名同理)。
 * 故意不写 sitemap。
 */
export default function robots(): MetadataRoute.Robots {
  return { rules: [{ userAgent: "*", disallow: "/" }] };
}
