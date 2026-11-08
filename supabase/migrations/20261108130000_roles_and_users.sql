-- Roles and users.
--   Super admin (public.super_admins): everything, for every client.
--   Client admin (organization_members.role 'owner' or 'admin'): their own company; adds Viewers and Editors,
--     within the number of users their licence allows (client_licenses.max_users), while the account and
--     licence are in good standing.
--   Editor (role 'member'): changes cameras, sites and PC names; no users, billing or pairing.
--   Viewer (role 'viewer'): sees everything in their company, changes nothing.
-- Users are created, changed and removed only by the manage-users function (it holds the rules); these
-- policies give the super admin direct control of every client's data and editors their edit rights.

-- How many portal users a SaaS client may have (set per client on the Licences page).
alter table public.client_licenses add column if not exists max_users integer not null default 5 check (max_users between 1 and 1000);

-- Seats and standing of a company: used by manage-users and shown on the Users pages.
create or replace function private.org_user_allowance(target_org uuid)
returns table (used integer, max_users integer, can_add boolean, reason text)
language sql stable security definer set search_path to '' as $$
  with o as (select id, status from public.organizations where id = target_org),
       l as (select status, expires_on, max_users from public.client_licenses
             where organization_id = target_org and edition = 'saas' order by issued_on desc nulls last, created_at desc limit 1),
       u as (select count(*)::int n from public.organization_members where organization_id = target_org)
  select u.n,
         coalesce(l.max_users, 5),
         (o.status in ('active', 'trial') and coalesce(l.status, 'active') = 'active'
          and (l.expires_on is null or l.expires_on >= current_date) and u.n < coalesce(l.max_users, 5)),
         case when o.id is null then 'Company not found.'
              when o.status not in ('active', 'trial') then 'This account is ' || o.status || '. Contact your provider.'
              when l.status = 'revoked' then 'The licence was revoked. Contact your provider.'
              when l.expires_on < current_date then 'The licence expired on ' || l.expires_on || '. Contact your provider.'
              when u.n >= coalesce(l.max_users, 5) then 'All ' || coalesce(l.max_users, 5) || ' user places are taken. Ask your provider for more.'
              else '' end
  from u left join o on true left join l on true
$$;
revoke execute on function private.org_user_allowance(uuid) from public, anon;
grant execute on function private.org_user_allowance(uuid) to authenticated;

-- Super admin: full control of every client's data (reads already exist; these add the writes).
create policy superadmin_members_select on public.organization_members for select to authenticated using (private.is_super_admin());
create policy superadmin_members_write on public.organization_members for all to authenticated
  using (private.is_super_admin()) with check (private.is_super_admin());
create policy superadmin_sources_write on public.video_sources for all to authenticated
  using (private.is_super_admin()) with check (private.is_super_admin());
create policy superadmin_sites_write on public.sites for all to authenticated
  using (private.is_super_admin()) with check (private.is_super_admin());
create policy superadmin_edge_devices_write on public.edge_devices for all to authenticated
  using (private.is_super_admin()) with check (private.is_super_admin());
create policy superadmin_profiles_select on public.profiles for select to authenticated using (private.is_super_admin());
create policy superadmin_subscriptions_write on public.subscriptions for all to authenticated
  using (private.is_super_admin()) with check (private.is_super_admin());

-- Editors change cameras, sites and PC names in their own company.
create policy video_sources_editor_write on public.video_sources for all to authenticated
  using (private.org_role(organization_id) = 'member') with check (private.org_role(organization_id) = 'member');
create policy sites_editor_update on public.sites for update to authenticated
  using (private.org_role(organization_id) = 'member') with check (private.org_role(organization_id) = 'member');
create policy edge_devices_editor_update on public.edge_devices for update to authenticated
  using (private.org_role(organization_id) = 'member') with check (private.org_role(organization_id) = 'member');

-- Editors may only rename a PC (not move it, disable it or change its token).
create or replace function private.editor_device_update_guard()
returns trigger language plpgsql security definer set search_path to '' as $$
begin
  if private.org_role(old.organization_id) = 'member' and not private.is_super_admin()
     and (new.organization_id, new.site_id, new.device_token_hash, new.device_key_hash, new.status)
         is distinct from (old.organization_id, old.site_id, old.device_token_hash, old.device_key_hash, old.status) then
    raise exception 'Editors can only rename a PC.' using errcode = '42501';
  end if;
  return new;
end $$;
revoke execute on function private.editor_device_update_guard() from public, anon, authenticated;
drop trigger if exists edge_devices_editor_guard on public.edge_devices;
create trigger edge_devices_editor_guard before update on public.edge_devices
  for each row execute function private.editor_device_update_guard();

-- Seats and standing of a company, for its members, super admins and the manage-users function.
create or replace function public.org_user_allowance(target_org uuid)
returns table (used integer, max_users integer, can_add boolean, reason text)
language plpgsql stable security definer set search_path to '' as $$
begin
  if not (private.is_org_member(target_org) or private.is_super_admin() or (select auth.role()) = 'service_role') then
    raise exception 'not authorized' using errcode = '42501';
  end if;
  return query select * from private.org_user_allowance(target_org);
end $$;
revoke execute on function public.org_user_allowance(uuid) from public, anon;
grant execute on function public.org_user_allowance(uuid) to authenticated, service_role;
