-- How many posts go out a day when the owner doesn't pick them all (owner,
-- 2026-10-19: "I can keep 2, 3…"): the automatic pick tops the day up to this many,
-- the owner's own picks counting towards it.

alter table channels
  add column daily_auto_count int not null default 1 check (daily_auto_count between 1 and 10);
