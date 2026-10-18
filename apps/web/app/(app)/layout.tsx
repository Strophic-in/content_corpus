import Link from "next/link";

import { workspace } from "@/lib/channels";
import { requireUser } from "@/lib/session";

import { BottomTabs, ChannelSwitcher, DesktopNav } from "./nav";
import { SignOutButton } from "./sign-out-button";

// One layout, two feels: on a desktop a top bar with links; on a phone (or the
// installed app) no top bar at all — pages carry their own title and channel
// picker, and the tab bar at the bottom is the navigation, like a native app.
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const user = await requireUser();
  const { channels, active } = await workspace(user.id);
  return (
    <div className="flex flex-1 flex-col">
      <header className="sticky top-0 z-30 hidden border-b border-border bg-surface/95 backdrop-blur md:block">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-4 px-4">
          <Link href="/discover" className="font-semibold tracking-tight">Content Corpus</Link>
          <ChannelSwitcher channels={channels.map(({ id, name }) => ({ id, name }))} activeId={active.id} />
          <DesktopNav />
          <div className="ml-auto flex items-center gap-3 text-sm text-muted">
            <span className="hidden lg:inline">{user.email}</span>
            <SignOutButton />
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 pt-[calc(env(safe-area-inset-top)+1.25rem)] pb-28 md:py-8 has-[.full-bleed]:max-w-none lg:has-[.full-bleed]:px-8">{children}</main>
      <BottomTabs />
    </div>
  );
}
