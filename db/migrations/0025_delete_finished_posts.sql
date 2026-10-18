-- A finished reel that was never scheduled or posted can be deleted too (owner,
-- 2026-10-18: drafts and reels he is not interested in, from the calendar).
--
-- Still never: a post being rendered or assembled (its jobs are running), and one
-- scheduled or published (it is, or is about to be, on a platform). Deleting cascades
-- to its scripts, shots, jobs and publish attempts; its files are swept by the worker
-- (sweep_intermediates: objects whose post is gone).

drop policy own_delete on posts;
create policy own_delete on posts for delete
  using (user_id = current_setting('app.user_id', true)
         and status in ('draft','scripting','awaiting_approval','approved','failed','cancelled',
                        'ready','needs_review'));
