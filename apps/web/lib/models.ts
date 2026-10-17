// Which of the key's OpenAI models suit which task. The full list is stored
// (app_settings.openai_models, refreshed daily by the ideas worker); each menu filters it.

// Not text-in/text-out: never offered for scripts, ideas or reading videos.
const NOT_FOR_TEXT = /(embed|tts|whisper|transcribe|audio|realtime|dall-e|image|moderation|search|computer-use|codex)/i;

export function textModels(all: string[]): string[] {
  return all.filter((id) => !NOT_FOR_TEXT.test(id)).sort();
}

/** Models that draw pictures (AI versions of a post's pictures). */
export function imageModels(all: string[]): string[] {
  return all.filter((id) => /^(gpt-image|dall-e)/i.test(id)).sort();
}
