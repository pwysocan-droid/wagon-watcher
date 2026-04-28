import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "wagon-watcher · inventory",
  description: "E-Class wagon CPO watcher — current MBUSA inventory.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        {/* JetBrains Mono + Inter from Google Fonts. Per PROJECT.md these
            are the project's open-source defaults; commercial faces (GT
            America, Söhne, etc.) are listed in the spec but not licensed
            for this project. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@100;200;400;500;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
