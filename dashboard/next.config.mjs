/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 不对外报框架名
  poweredByHeader: false,
  // 全站不让搜索引擎收录(公开页、内部座舱、接口、Vercel 预览域名都算)。
  // 同一个决定的另外两处：app/layout.tsx 的 robots 元信息、app/robots.ts 的 robots.txt。
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow, noarchive" }],
      },
    ];
  },
};

export default nextConfig;
