import type { Metadata } from "next";
import { connection } from "next/server";

/**
 * 404 页。页面上的字和样式照抄 Next 自带的那一版(next/dist/client/components/http-access-fallback/error-fallback.js，
 * Next 14 和 16 自带的这一版画出来一样)，看到的和升级前一模一样。自己写一份只为把两处升级带来的变化改回 Next 14 时的样子(D-161)：
 * 1. 标签页标题：Next 16 + React 19 下，自带 404 页的 <title> 排到了根布局的站点标题后面，浏览器标签显示成站点标题。
 *    这里用 metadata 把标题定成 "404: This page could not be found."，和升级前一样；自带那版里的 <title> 不再写。
 * 2. 不许缓存：Next 16 把 404 页构建成静态页，直接访问 /_not-found 或 /%62oard 这种编码过的地址时会带
 *    Cache-Control: s-maxage=31536000(前面要是有共享缓存，能存一年)。await connection() 让 404 页每次现做，
 *    回到和升级前一样的 private, no-store。
 * 页面上只有写死的字，不取数、不读 cookie。
 */
export const metadata: Metadata = { title: "404: This page could not be found." };

export default async function NotFound() {
  await connection();
  return (
    <div
      style={{
        fontFamily: 'system-ui,"Segoe UI",Roboto,Helvetica,Arial,sans-serif,"Apple Color Emoji","Segoe UI Emoji"',
        height: "100vh",
        textAlign: "center",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div>
        <style
          dangerouslySetInnerHTML={{
            __html:
              "body{color:#000;background:#fff;margin:0}.next-error-h1{border-right:1px solid rgba(0,0,0,.3)}@media (prefers-color-scheme:dark){body{color:#fff;background:#000}.next-error-h1{border-right:1px solid rgba(255,255,255,.3)}}",
          }}
        />
        <h1
          className="next-error-h1"
          style={{ display: "inline-block", margin: "0 20px 0 0", padding: "0 23px 0 0", fontSize: 24, fontWeight: 500, verticalAlign: "top", lineHeight: "49px" }}
        >
          404
        </h1>
        <div style={{ display: "inline-block" }}>
          <h2 style={{ fontSize: 14, fontWeight: 400, lineHeight: "49px", margin: 0 }}>This page could not be found.</h2>
        </div>
      </div>
    </div>
  );
}
