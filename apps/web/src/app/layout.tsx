import type { Metadata } from "next";

import { Nav } from "@/components/Nav";

import "./globals.css";

export const metadata: Metadata = {
  title: "LotLoops",
  description: "Grade GovDeals bulk-computer auctions on what they are worth",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <Nav />
        <div className="shell">{children}</div>
      </body>
    </html>
  );
}
