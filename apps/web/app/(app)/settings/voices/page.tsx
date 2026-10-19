import Link from "next/link";

import { asUser } from "@/lib/db";
import { requireUser } from "@/lib/session";
import { sample, voices } from "@/lib/voices";

import { VoicesBoard } from "./voices-board";

export const metadata = { title: "Voices · Content Corpus" };

// Settings → Voices: every narrator voice, with a sample to hear; the ones switched
// on are what Jev picks from for each post (or one fixed voice).
export default async function VoicesPage() {
  const user = await requireUser();
  const st = await asUser(user.id, async (db) => {
    await db.query("select api.ensure_settings()");
    return (await db.query("select voice_mode, voices_enabled, fixed_voice from app_settings")).rows[0] as
      { voice_mode: "auto" | "fixed"; voices_enabled: string[]; fixed_voice: string | null };
  });
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <Link href="/settings" className="text-sm text-muted hover:text-foreground">← Settings</Link>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Voices</h1>
        <p className="mt-1 text-sm text-muted">Switch on the voices you like. For each narrated post Jev picks the best of them
          for the story: a free voice for English, an AI voice for Hindi. AI voices also get their tone from the script —
          urgent for breaking news, calm for science, slow and respectful for a tragedy. Press ▶ to hear one.</p>
      </div>
      <VoicesBoard
        voices={voices().map((v) => ({ id: v.id, engine: v.engine, name: v.name, gender: v.gender, accent: v.accent,
                                       languages: v.languages, tone: v.tone, sample: sample(v.id) }))}
        enabled={st.voices_enabled} mode={st.voice_mode} fixedVoice={st.fixed_voice} />
    </div>
  );
}
