import "server-only";

import { asUser } from "./db";

export type Platform = "youtube" | "instagram";
export const PLATFORM_NAMES: Record<Platform, string> = { youtube: "YouTube", instagram: "Instagram" };

export type PublishTarget = {
  platform: Platform;
  account: { handle: string | null; display_name: string | null; status: string } | null;
  // The publish-lane job: state, when it runs, why it last failed.
  job: { state: string; not_before: Date; error: { message?: string; stage?: string } | null;
         privacy: string | null; due: boolean } | null;
  // The newest attempt, a live one first: what actually reached the platform.
  attempt: { state: string; remote_url: string | null; privacy: string | null } | null;
};

export type PublishInfo = {
  targets: PublishTarget[];
  youtubePrivacy: string;
  /** The post's planned time as `YYYY-MM-DDTHH:MM` in its timezone, if still ahead. */
  plannedLocal: string | null;
  tz: string;
};

/** Where a post can go and where it has got to, per platform of its channel. */
export async function publishInfo(userId: string, postId: string, channelId: string | null): Promise<PublishInfo> {
  return asUser(userId, async (db) => {
    const accounts = channelId
      ? (await db.query("select platform, handle, display_name, status from channel_accounts where channel_id = $1",
                        [channelId])).rows
      : [];
    const jobs = (await db.query(
      `select payload->>'platform' as platform, state, not_before, error, payload->>'privacy' as privacy,
              not_before <= now() + interval '1 minute' as due
         from jobs where post_id = $1 and lane = 'publish'`, [postId])).rows;
    const attempts = (await db.query(
      `select distinct on (platform) platform, state, remote_url, privacy
         from publish_attempts where post_id = $1
        order by platform, (state = 'live') desc, created_at desc`, [postId])).rows;
    const post = (await db.query(
      `select publish_tz,
              case when publish_at > now()
                   then to_char(publish_at at time zone publish_tz, 'YYYY-MM-DD"T"HH24:MI') end as planned
         from posts where id = $1`, [postId])).rows[0];
    const s = (await db.query("select youtube_privacy from app_settings")).rows[0];
    const targets = (["youtube", "instagram"] as Platform[]).map((platform) => {
      const a = accounts.find((x) => x.platform === platform);
      const j = jobs.find((x) => x.platform === platform);
      const t = attempts.find((x) => x.platform === platform);
      return {
        platform,
        account: a ? { handle: a.handle, display_name: a.display_name, status: a.status } : null,
        job: j ? { state: j.state, not_before: j.not_before, error: j.error, privacy: j.privacy, due: j.due } : null,
        attempt: t ? { state: t.state, remote_url: t.remote_url, privacy: t.privacy } : null,
      };
    });
    return { targets, youtubePrivacy: s?.youtube_privacy ?? "private", plannedLocal: post?.planned ?? null,
             tz: post?.publish_tz ?? "Asia/Kolkata" };
  });
}
