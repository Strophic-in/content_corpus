-- The contact page's messages (owner, 2026-10-20: "the contact thing is not working" -
-- it only opened the visitor's own mail app, which many devices don't have). A message
-- is kept here and shown to the owner in Admin; an email copy goes out too when the
-- server can send mail.
--
-- api.contact_message is callable by anyone (the page is public), so it limits itself:
-- a few messages an hour from one sender (by a hash of their address, never the
-- address itself), and a ceiling a day for everyone.

create table contact_messages (
  id         uuid primary key default gen_random_uuid(),
  name       text not null default '' check (length(name) <= 120),
  email      text not null check (length(email) between 3 and 254),
  topic      text not null default '' check (length(topic) <= 80),
  message    text not null check (length(message) between 1 and 5000),
  sender     text not null default '',          -- a hash of the sender's network address, for rate limits
  emailed    boolean not null default false,
  read_at    timestamptz,
  created_at timestamptz not null default now()
);
create index contact_messages_recent on contact_messages (created_at desc);
alter table contact_messages enable row level security;   -- reached only through the functions below

create or replace function api.contact_message(p_name text, p_email text, p_topic text, p_message text,
                                               p_sender text) returns uuid
language plpgsql security definer set search_path = '' as $fn$
declare id uuid;
begin
  if coalesce(btrim(p_email), '') !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then
    raise exception 'give an email address we can reply to' using errcode = '22023';
  end if;
  if length(btrim(coalesce(p_message, ''))) < 2 then
    raise exception 'write a message' using errcode = '22023';
  end if;
  if (select count(*) from public.contact_messages
       where sender = coalesce(p_sender, '') and created_at > now() - interval '1 hour') >= 5
     or (select count(*) from public.contact_messages where created_at > now() - interval '1 day') >= 300 then
    raise exception 'too many messages just now - try again later, or write to the email address'
      using errcode = '54000';
  end if;
  insert into public.contact_messages (name, email, topic, message, sender)
  values (left(btrim(coalesce(p_name, '')), 120), left(btrim(p_email), 254), left(btrim(coalesce(p_topic, '')), 80),
          left(btrim(p_message), 5000), coalesce(p_sender, ''))
  returning contact_messages.id into id;
  return id;
end $fn$;

create or replace function api.contact_emailed(p_id uuid) returns void
language sql security definer set search_path = '' as $fn$
  update public.contact_messages set emailed = true where id = p_id;
$fn$;

create or replace function api.admin_contact_messages()
returns table (id uuid, name text, email text, topic text, message text, emailed boolean, read_at timestamptz,
               created_at timestamptz)
language plpgsql stable security definer set search_path = '' as $fn$
begin
  perform private.require_owner();
  return query select m.id, m.name, m.email, m.topic, m.message, m.emailed, m.read_at, m.created_at
                 from public.contact_messages m order by m.created_at desc limit 200;
end $fn$;

create or replace function api.admin_read_contact_message(p_id uuid, p_read boolean) returns void
language plpgsql security definer set search_path = '' as $fn$
begin
  perform private.require_owner();
  update public.contact_messages set read_at = case when p_read then coalesce(read_at, now()) end where id = p_id;
end $fn$;
