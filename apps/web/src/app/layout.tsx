import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: "pc-part-scan",
  description: "GovDeals bulk-computer auction workbench",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <nav className="topnav">
            <span className="brand">pc-part-scan</span>
            <Link href="/">Board</Link>
            <Link href="/sold">Sold</Link>
            <Link href="/models">Models</Link>
            <Link href="/ops">Ops</Link>
          </nav>
          {children}
        </div>
      </body>
    </html>
  );
}
