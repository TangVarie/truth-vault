import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // v4 编辑级 brutalist 调色(Saving Goal 灵感 + 1 个 coral 点睛色)
        ink:      "#0a0a0f",
        paper:    "#f4f1ea",
        coral:    "#E8765A",   // ⭐ 唯一点睛色(不是 teal)
        "coral-deep": "#C9523A",
        sage:     "#C8D4B8",
        olive:    "#9A9750",
        lavender: "#A6A2D8",
        bone:     "#EFE9DC",
        carbon:   "#1c1c22",
        // 兼容旧引用(组件内部还有用到的)
        bywood:   { blue: "#1b4fd1", navy: "#0a1024", ink: "#0a0e1a", red: "#cc2128" },
        flywheel: { bg: "#0a0a0f", card: "#131319", accent: "#E8765A", warn: "#fbbf24", danger: "#f87171" },
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
