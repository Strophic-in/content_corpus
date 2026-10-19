import Link from "next/link";

import { asUser } from "@/lib/db";
import { requireUser } from "@/lib/session";
import { sample, voices, voiceStyles } from "@/lib/voices";

import { VoicesBoard } from "./voices-board";

export const metadata = { title: "Voices · Content Corpus" };

// Settings → Voices: every narrator voice and voice style, with a sample to hear;
// the ones switched on are what Jev picks from for each post (or one fixed voice).
export default async function VoicesPage() {
  const user = await requireUser();
  const st = await asUser(user.id, async (db) => {
    await db.query("select api.ensure_settings()");
    return (await db.query(
      "select voice_mode, voices_enabled, voice_styles_enabled, fixed_voice, fixed_voice_style from app_settings")).rows[0] as
      { voice_mode: "auto" | "fixed"; voices_enabled: string[]; voice_styles_enabled: string[]; fixed_voice: string | null;
        fixed_voice_style: string | null };
  });
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <Link href="/settings" className="text-sm text-muted hover:text-foreground">← Settings</Link>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Voices</h1>
        <p className="mt-1 text-sm text-muted">Switch on the voices and styles you like. For each narrated post Jev picks the best of
          them for the story and the channel&apos;s language. Press ▶ to hear one.</p>
      </div>
      <VoicesBoard
        voices={voices().map((v) => ({ id: v.id, engine: v.engine, name: v.name, gender: v.gender, accent: v.accent,
                                       languages: v.languages, tone: v.tone, sample: sample("voice", v.id) }))}
        styles={voiceStyles().map((s) => ({ id: s.style_id, name: s.name, description: s.description,
                                            hindiOnly: (s.languages ?? []).join() === "hi", sample: sample("style", s.style_id),
                                            group: s.group ?? "Other", expressive: Boolean(s.expressive) }))}
        enabled={st.voices_enabled} stylesOn={st.voice_styles_enabled} mode={st.voice_mode}
        fixedVoice={st.fixed_voice} fixedStyle={st.fixed_voice_style} />
    </div>
  );
}
