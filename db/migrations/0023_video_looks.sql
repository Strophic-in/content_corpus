-- Video looks: how a post's generated shots look (prompts/looks/<id>.json).
--
--   channels.video_look  'auto' (Jev picks per post), 'format' (each format's own
--                        look text, as before), or one look's id.
--   posts.look_id        the look chosen for the post when its script is written
--                        (kept across rewrites); posts.look_why says why.
-- Existing channels start on auto (owner's choice, 2026-10-18).

alter table channels add column video_look text not null default 'auto'
  check (video_look ~ '^[a-z0-9_]{3,40}$');
alter table posts add column look_id text check (look_id ~ '^[a-z0-9_]{3,40}$'),
                  add column look_why text;
