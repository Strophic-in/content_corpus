-- Phase 5 (baseline): more than one person can use Content Corpus.
--
--   memberships  one row per account: role (owner | member), status (pending until
--                an owner approves | active | suspended) and a monthly spending
--                limit in paise (null = none). Everyone here before this migration
--                signed in under the owner-only rule, so they are owners.
--   app_config   whether new accounts wait for approval (yes by default) and the
--                limit a new member starts with.
--
-- private.caller() — which every api function uses to know who is asking — now
-- refuses an account that isn't active, so a pending or suspended account can't
-- start work even by calling the API directly. Paid work (a script, a render, an
-- idea batch) checks the month's spending limit first. The workers' shared costs
-- (the GPU account, storage) are bounded by those limits.

create table memberships (
  user_id             text primary key references "user"(id) on delete cascade,
  role                text not null default 'member' check (role in ('owner','member')),
  status              text not null default 'pending' check (status in ('pending','active','suspended')),
  monthly_limit_paise int check (monthly_limit_paise >= 0),
  created_at          timestamptz not null default now(),
  decided_at          timestamptz,
  decided_by          text
);
alter table memberships enable row level security;
create policy own on memberships for select using (user_id = current_setting('app.user_id', true));

create table app_config (
  id                         boolean primary key default true check (id),
  signups_need_approval      boolean not null default true,
  member_monthly_limit_paise int not null default 50000 check (member_monthly_limit_paise >= 0)
);
insert into app_config default values;

insert into memberships (user_id, role, status, decided_at)
select id, 'owner', 'active', now() from "user";

create or replace function private.new_membership() returns trigger
language plpgsql security definer set search_path = '' as $fn$
declare cfg public.app_config;
begin
  select * into cfg from public.app_config;
  insert into public.memberships (user_id, role, status, monthly_limit_paise)
  values (new.id, 'member',
          case when coalesce(cfg.signups_need_approval, true) then 'pending' else 'active' end,
          cfg.member_monthly_limit_paise)
  on conflict (user_id) do nothing;
  return new;
end $fn$;

create trigger user_membership after insert on "user"
  for each row execute function private.new_membership();

create or replace function private.caller() returns text
language plpgsql stable security definer set search_path = '' as $fn$
declare
  u  text := nullif(current_setting('app.user_id', true), '');
  st text;
begin
  if u is null then
    raise exception 'no signed-in user for this transaction' using errcode = '28000';
  end if;
  select status into st from public.memberships where user_id = u;
  if st is distinct from 'active' then
    raise exception 'this account is %', coalesce(st, 'not set up') using errcode = '42501';
  end if;
  return u;
end $fn$;

-- ── spending limits ──────────────────────────────────────────────────────────

create or replace function private.spent_month_paise(p_user_id text) returns bigint
language sql stable security definer set search_path = '' as $fn$
  with tz as (select coalesce((select timezone from public.app_settings where user_id = p_user_id),
                              'Asia/Kolkata') as z)
  select coalesce(sum(coalesce(c.inr_paise, 0)
                      + coalesce(c.usd_micros, 0) * coalesce(c.fx_usd_inr, 85) / 10000), 0)::bigint
    from public.costs c, tz
   where c.user_id = p_user_id
     and c.created_at >= (date_trunc('month', now() at time zone tz.z) at time zone tz.z);
$fn$;

create or replace function private.check_quota(p_user_id text) returns void
language plpgsql stable security definer set search_path = '' as $fn$
declare lim int;
begin
  select monthly_limit_paise into lim from public.memberships where user_id = p_user_id;
  if lim is not null and private.spent_month_paise(p_user_id) >= lim then
    raise exception 'this month''s spending limit (₹%) is reached — ask the owner to raise it', lim / 100
      using errcode = '55000';
  end if;
end $fn$;

create or replace function api.generate_script(p_post_id uuid) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
begin
  perform private.owned_post(p_post_id);
  perform private.check_quota(private.caller());
  return private.generate_script(p_post_id, 'user:' || private.caller());
end $fn$;

create or replace function api.request_render(p_post_id uuid) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
begin
  perform private.owned_post(p_post_id);
  perform private.check_quota(private.caller());
  return private.request_render(p_post_id, 'user:' || private.caller());
end $fn$;

create or replace function api.request_category_ideas(p_category_id uuid) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare k public.categories := private.owned_category(p_category_id);
begin
  perform private.check_quota(k.user_id);
  return private.queue_category_ideas(k, 'manual',
    format('suggest_ideas:cat:%s:%s', k.id, to_char(now(), 'YYYYMMDDHH24MI')), now(), 60);
end $fn$;

create or replace function api.request_channel_ideas(p_channel_id uuid) returns int
language plpgsql security definer set search_path = '' as $fn$
declare
  c public.channels := private.owned_channel(p_channel_id);
  k public.categories;
  n int := 0;
begin
  perform private.check_quota(c.user_id);
  for k in select * from public.categories where channel_id = c.id and enabled order by created_at loop
    perform private.queue_category_ideas(k, 'manual',
      format('suggest_ideas:cat:%s:%s', k.id, to_char(now(), 'YYYYMMDDHH24MI')), now(), 60);
    n := n + 1;
  end loop;
  return n;
end $fn$;

-- ── the owner's admin ────────────────────────────────────────────────────────

create or replace function private.require_owner() returns text
language plpgsql stable security definer set search_path = '' as $fn$
declare u text := private.caller();
begin
  if not exists (select 1 from public.memberships where user_id = u and role = 'owner') then
    raise exception 'only the owner can do this' using errcode = '42501';
  end if;
  return u;
end $fn$;

create or replace function api.admin_members()
returns table (user_id text, email text, name text, role text, status text, monthly_limit_paise int,
               month_paise bigint, storage_bytes bigint, created_at timestamptz)
language plpgsql stable security definer set search_path = '' as $fn$
begin
  perform private.require_owner();
  return query
    select u.id, u.email, u.name, m.role, m.status, m.monthly_limit_paise, private.spent_month_paise(u.id),
           coalesce((select sum(s.bytes) from public.storage_objects s
                      where s.user_id = u.id and s.state = 'stored'), 0)::bigint,
           u."createdAt"
      from public."user" u join public.memberships m on m.user_id = u.id
     order by (m.status = 'pending') desc, u."createdAt" desc;
end $fn$;

create or replace function api.admin_set_member(p_user_id text, p_status text, p_monthly_limit_paise int)
returns public.memberships
language plpgsql security definer set search_path = '' as $fn$
declare
  me text := private.require_owner();
  m  public.memberships;
begin
  if p_status not in ('pending','active','suspended') then
    raise exception 'unknown status %', p_status using errcode = '22023';
  end if;
  if p_monthly_limit_paise is not null and p_monthly_limit_paise < 0 then
    raise exception 'a limit can''t be negative' using errcode = '22023';
  end if;
  select * into m from public.memberships where user_id = p_user_id for update;
  if not found then
    raise exception 'no such account' using errcode = 'P0002';
  end if;
  if m.role = 'owner' then
    raise exception 'owners are set by AUTH_ALLOWED_EMAILS, not here' using errcode = '42501';
  end if;
  update public.memberships set status = p_status, monthly_limit_paise = p_monthly_limit_paise,
                                decided_at = now(), decided_by = me
   where user_id = p_user_id returning * into m;
  return m;
end $fn$;

create or replace function api.admin_config() returns public.app_config
language plpgsql stable security definer set search_path = '' as $fn$
declare cfg public.app_config;
begin
  perform private.require_owner();
  select * into cfg from public.app_config;
  return cfg;
end $fn$;

create or replace function api.admin_set_config(p_signups_need_approval boolean, p_member_monthly_limit_paise int)
returns public.app_config
language plpgsql security definer set search_path = '' as $fn$
declare cfg public.app_config;
begin
  perform private.require_owner();
  update public.app_config set signups_need_approval = p_signups_need_approval,
                               member_monthly_limit_paise = p_member_monthly_limit_paise
  returning * into cfg;
  return cfg;
end $fn$;
