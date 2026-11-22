-- Trial: what the Business plan has, for 14 days, once per email.
--   * A client created on Trial (status 'trial') gets trial_ends_at = 14 days later.
--   * After that date the trial has ended: its PCs get every feature switched off and refuse sign-in (edge-agent-control,
--     edge-sync), adding users stops, and the portal only shows "Choose a plan" until the client pays (Stripe checkout;
--     the stripe-webhook then sets the account active on the chosen plan).
--   * trial_emails remembers every email that started a trial (kept when the account or company is deleted), so the
--     same email can't get a second trial (manage-users create_client refuses it).

alter table public.organizations add column if not exists trial_ends_at timestamptz;

create or replace function private.set_trial_end()
returns trigger language plpgsql set search_path to '' as $$
begin
  if new.status = 'trial' and new.trial_ends_at is null then
    new.trial_ends_at := now() + interval '14 days';
  end if;
  return new;
end $$;
drop trigger if exists organizations_trial_end on public.organizations;
create trigger organizations_trial_end before insert or update of status on public.organizations
  for each row execute function private.set_trial_end();

-- Trial clients that already exist get their 14 days from now.
update public.organizations set trial_ends_at = now() + interval '14 days' where status = 'trial' and trial_ends_at is null;

-- true when this company's trial has ended (and it hasn't chosen a plan since).
create or replace function public.org_trial_expired(target_org uuid)
returns boolean language sql stable security definer set search_path to '' as $$
  select coalesce((select status = 'trial' and trial_ends_at is not null and trial_ends_at < now()
                   from public.organizations where id = target_org), false)
$$;
revoke execute on function public.org_trial_expired(uuid) from public, anon;
grant execute on function public.org_trial_expired(uuid) to authenticated, service_role;

create table if not exists public.trial_emails (
  email text primary key check (email = lower(email)),
  organization_id uuid,
  started_at timestamptz not null default now()
);
alter table public.trial_emails enable row level security;
drop policy if exists "super admins read trial emails" on public.trial_emails;
create policy "super admins read trial emails" on public.trial_emails for select to authenticated
  using ((select private.is_super_admin()));

-- Trial = Business (features and limits, DJI Docks included).
insert into public.plan_features (plan_code, feature_key, enabled, limit_value)
select 'trial', feature_key, enabled, limit_value from public.plan_features where plan_code = 'business'
on conflict (plan_code, feature_key) do update set enabled = excluded.enabled, limit_value = excluded.limit_value;

-- No new users once the trial has ended.
create or replace function private.org_user_allowance(target_org uuid)
returns table (used integer, max_users integer, can_add boolean, reason text)
language sql stable security definer set search_path to '' as $$
  with o as (select id, status, trial_ends_at from public.organizations where id = target_org),
       l as (select status, expires_on, max_users from public.client_licenses
             where organization_id = target_org and edition = 'saas' order by issued_on desc nulls last, created_at desc limit 1),
       u as (select count(*)::int n from public.organization_members where organization_id = target_org)
  select u.n,
         coalesce(l.max_users, 5),
         (o.status in ('active', 'trial') and not (o.status = 'trial' and o.trial_ends_at < now())
          and coalesce(l.status, 'active') = 'active'
          and (l.expires_on is null or l.expires_on >= current_date) and u.n < coalesce(l.max_users, 5)),
         case when o.id is null then 'Company not found.'
              when o.status = 'trial' and o.trial_ends_at < now() then 'The 14-day trial has ended. Choose a plan in the portal.'
              when o.status not in ('active', 'trial') then 'This account is ' || o.status || '. Contact your provider.'
              when l.status = 'revoked' then 'The licence was revoked. Contact your provider.'
              when l.expires_on < current_date then 'The licence expired on ' || l.expires_on || '. Contact your provider.'
              when u.n >= coalesce(l.max_users, 5) then 'All ' || coalesce(l.max_users, 5) || ' user places are taken. Ask your provider for more.'
              else '' end
  from u left join o on true left join l on true
$$;
