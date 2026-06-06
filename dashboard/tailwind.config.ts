import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // BYWOOD 芭梧 品牌色(取自名片)
        bywood: {
          blue: "#1b4fd1", // 主蓝(扶摇 ROC 区块)
          navy: "#0a1024", // 深底
          ink: "#0a0e1a",
          red: "#cc2128", // 强调红
        },
        // 看板主题
        flywheel: {
          bg: "#0a0e1a",
          card: "#121829",
          accent: "#5eead4",
          warn: "#fbbf24",
          danger: "#f87171",
        },
      },
      animation: {
        "spin-slow": "spin-slow 26s linear infinite",
        "spin-rev": "spin-rev 34s linear infinite",
        "gradient": "gradient-shift 14s ease infinite",
        "float": "float 7s ease-in-out infinite",
      },
      keyframes: {
        "spin-slow": { to: { transform: "rotate(360deg)" } },
        "spin-rev": { to: { transform: "rotate(-360deg)" } },
        "gradient-shift": {
          "0%,100%": { backgroundPosition: "0% 50%" },
          "50%": { backgroundPosition: "100% 50%" },
        },
        float: {
          "0%,100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-8px)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
