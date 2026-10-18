"use server";

import { refresh } from "next/cache";
import { z } from "zod";

import { asUser } from "@/lib/db";
import { friendly } from "@/lib/errors";
import { requireUser } from "@/lib/session";
import { wakeWorker } from "@/lib/wake";

// The Library table's actions, on one post or many. Each post is its own call, so
// one refusal ("it is rendering") never stops the rest; the reply says what
// happened to each.

const Input = z.object({
  ids: z.array(z.string().uuid()).min(1).max(200),
  action: z.enum(["go_ahead", "approve", "write", "delete"]),
});

export type BulkResult = { ok: boolean; message: string; failed: { id: string; error: string }[] };

const DONE = { go_ahead: "on their way to a video", approve: "approved", write: "writing scripts", delete: "deleted" };

export async function bulkPostAction(input: z.input<typeof Input>): Promise<BulkResult> {
  const user = await requireUser();
  const parsed = Input.safeParse(input);
  if (!parsed.success) return { ok: false, message: "Pick some posts first.", failed: [] };
  const { ids, action } = parsed.data;
  const failed: BulkResult["failed"] = [];
  let done = 0;
  for (const id of ids) {
    try {
      await asUser(user.id, async (db) => {
        if (action === "go_ahead") {
          await db.query("select api.go_ahead($1)", [id]);
        } else if (action === "write") {
          await db.query("select api.generate_script($1)", [id]);
        } else if (action === "approve") {
          const s = (await db.query(
            `select id from scripts where post_id = $1 and state = 'awaiting_approval' order by version desc limit 1`,
            [id])).rows[0];
          if (!s) throw new Error("no script is waiting for approval");
          await db.query("select api.approve_script($1)", [s.id]);
        } else {
          const r = await db.query("delete from posts where id = $1", [id]);
          if (!r.rowCount) throw new Error("only a post that is not rendered yet can be deleted");
        }
      });
      done++;
    } catch (err) {
      failed.push({ id, error: err instanceof Error && !("code" in err) ? err.message : friendly(err) });
    }
  }
  if (done && action !== "delete") await wakeWorker();
  refresh();
  const what = `${done} ${done === 1 ? "post" : "posts"} ${DONE[action]}`;
  return { ok: failed.length === 0, message: failed.length ? `${what}; ${failed.length} could not be` : what, failed };
}
