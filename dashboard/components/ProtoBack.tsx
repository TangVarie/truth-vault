import Link from "next/link";

/** 各原型左下角固定的"返回对比"链接。 */
export default function ProtoBack({ dark = true }: { dark?: boolean }) {
  return (
    <Link
      href="/proto"
      style={{
        position: "fixed", left: 12, bottom: 12, zIndex: 50,
        fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase",
        fontFamily: "var(--font-geist-mono)", textDecoration: "none",
        padding: "6px 12px", borderRadius: 99,
        background: dark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.06)",
        color: dark ? "#fff" : "#111",
        border: dark ? "1px solid rgba(255,255,255,0.18)" : "1px solid rgba(0,0,0,0.12)",
        backdropFilter: "blur(6px)",
      }}
    >
      ← 原型对比
    </Link>
  );
}
