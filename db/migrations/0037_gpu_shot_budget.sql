-- At most this many shots of a video are generated on the GPU (owner, 2026-10-19:
-- "2 GPU shots for a video should be enough"); the writer makes the rest from the
-- pictures and footage collected for the story, charts and text cards. Formats that
-- can only be generated (characters speaking, POV scenes) are not held to it.

alter table app_settings
  add column max_gpu_shots int not null default 2 check (max_gpu_shots between 0 and 12);
