import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // 飞轮主题:深底 + 强调色
        flywheel: {
          bg: "#0a0e1a",
          card: "#121829",
          accent: "#5eead4",
          warn: "#fbbf24",
          danger: "#f87171",
        },
      },
    },
  },
  plugins: [],
};

export default config;
