"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTransition } from "react";

import { switchChannel } from "./channel-actions";

type Tab = { href: string; label: string; icon: React.ReactNode };

const I = (d: string) => (
  <svg viewBox="0 0 24 24" aria-hidden className="size-6" fill="none" stroke="currentColor" strokeWidth={1.8}
       strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>
);

export const TABS: Tab[] = [
  { href: "/discover", label: "Discover",
    icon: I("M12 3c.5 3.5 4 5.5 4 9.5a4 4 0 0 1-8 0c0-1.6.7-2.8 1.5-3.7.2 1.4 1 2.4 2 2.7C11 9 11.4 5.6 12 3Z") },
  { href: "/calendar", label: "Calendar", icon: I("M4 6h16v14H4zM4 10h16M9 3v4M15 3v4") },
  { href: "/library", label: "Library", icon: I("M5 4h5v16H5zM10 4h4v16h-4zM14.5 4.5l4.5 1.2-3.8 14.3-4.5-1.2") },
  { href: "/channels", label: "Channels", icon: I("M5 12a7 7 0 0 1 14 0M8.5 12a3.5 3.5 0 0 1 7 0M12 12v8") },
  { href: "/settings", label: "Settings",
    icon: I("M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM19 12l2-1-1-3-2 .3-1.3-1.3.3-2-3-1-1 2h-2l-1-2-3 1 .3 2L6 7.3 4 7l-1 3 2 1v2l-2 1 1 3 2-.3 1.3 1.3-.3 2 3 1 1-2h2l1 2 3-1-.3-2 1.3-1.3 2 .3 1-3-2-1Z") },
];

function isActive(path: string, href: string) {
  return path === href || path.startsWith(href + "/") || (href === "/calendar" && path.startsWith("/posts"))
    || (href === "/discover" && path.startsWith("/explore"));
}

export function DesktopNav() {
  const path = usePathname();
  return (
    <nav className="hidden gap-4 text-sm md:flex">
      {TABS.map((t) => (
        <Link key={t.href} href={t.href}
              className={isActive(path, t.href) ? "font-medium text-foreground" : "text-muted hover:text-foreground"}>
          {t.label}
        </Link>
      ))}
    </nav>
  );
}

/** The phone's tab bar: fixed at the bottom, above the home indicator. */
export function BottomTabs() {
  const path = usePathname();
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
      <div className="mx-auto grid max-w-lg grid-cols-5">
        {TABS.map((t) => {
          const on = isActive(path, t.href);
          return (
            <Link key={t.href} href={t.href}
                  className={`flex flex-col items-center gap-0.5 py-2 text-[11px] transition-colors ${on ? "text-accent" : "text-muted"}`}>
              <span className={`transition-transform duration-200 ${on ? "scale-110" : ""}`}>{t.icon}</span>
              {t.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

/** Switch the active channel. On a channel's Discover deck, go to the new channel's
 *  deck (its URL names the channel); anywhere else, re-render for the new channel. */
function useSwitch() {
  const router = useRouter();
  const path = usePathname();
  const [pending, start] = useTransition();
  const go = (id: string) => start(async () => {
    await switchChannel(id);
    if (path.startsWith("/discover/")) router.push(`/discover/${id}`);
    else router.refresh();
  });
  return [pending, go] as const;
}

/** The channel name as a tap-to-switch picker, for page titles (phones have no top bar). */
export function ChannelPicker({ channels, activeId }: { channels: { id: string; name: string }[]; activeId: string }) {
  const [pending, go] = useSwitch();
  const name = channels.find((c) => c.id === activeId)?.name ?? "";
  if (channels.length < 2) return <span className="font-medium text-foreground">{name}</span>;
  return (
    <span className="relative inline-flex items-center font-medium text-foreground">
      {name}<span aria-hidden className="ml-0.5 text-muted">▾</span>
      <select aria-label="Switch channel" value={activeId} disabled={pending}
              onChange={(e) => go(e.target.value)}
              className="absolute inset-0 cursor-pointer opacity-0">
        {channels.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
    </span>
  );
}

export function ChannelSwitcher({ channels, activeId }: { channels: { id: string; name: string }[]; activeId: string }) {
  const [pending, go] = useSwitch();
  if (channels.length < 2)
    return <span className="max-w-[45vw] truncate text-sm font-medium">{channels[0]?.name}</span>;
  return (
    <select aria-label="Channel" value={activeId} disabled={pending}
            onChange={(e) => go(e.target.value)}
            className="max-w-[45vw] truncate rounded-md border border-border bg-background px-2 py-1 text-sm font-medium outline-none focus:border-accent">
      {channels.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
    </select>
  );
}
