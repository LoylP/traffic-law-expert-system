import type { Metadata, Viewport } from "next";
import { Be_Vietnam_Pro } from "next/font/google";

import "./globals.css";

const beVietnam = Be_Vietnam_Pro({
  subsets: ["vietnamese", "latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-be-vietnam",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Trợ lý Luật Giao thông",
  description:
    "Hệ chuyên gia xác định hành vi vi phạm giao thông, mức phạt và giải thích căn cứ pháp lý.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

// Applies a saved theme before first paint to avoid a flash.
const THEME_SCRIPT = `try{var t=localStorage.getItem("traffic-law:theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="vi" className={beVietnam.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="antialiased">{children}</body>
    </html>
  );
}
