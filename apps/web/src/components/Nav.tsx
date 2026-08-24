"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Board" },
  { href: "/sold", label: "Sold" },
  { href: "/models", label: "Models" },
  { href: "/ops", label: "Ops" },
];

export function Nav() {
  const path = usePathname();
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link href="/" className="brand">
          Lot<span className="brand-accent">Loops</span>
        </Link>
        <nav aria-label="Main">
          {LINKS.map((l) => {
            // "/" would otherwise match every route
            const active =
              l.href === "/" ? path === "/" : path.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`navlink${active ? " active" : ""}`}
                aria-current={active ? "page" : undefined}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
