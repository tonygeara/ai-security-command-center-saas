-- Admin portal "Remove" buttons. Super admins only; every removal is written to the activity log.

-- A client PC and the cameras/drones registered through it. Its device token stops working.
create or replace function public.admin_remove_device(target_device uuid)
returns void language plpgsql security definer set search_path to '' as $$
declare d record;
begin
  if not private.is_super_admin() then raise exception 'not authorized'; end if;
  select id, organization_id, device_name, app_version into d from public.edge_devices where id = target_device;
  if d.id is null then raise exception 'PC not found'; end if;
  insert into public.audit_logs (organization_id, actor_user_id, action, target_type, target_id, metadata)
  values (d.organization_id, auth.uid(), 'pc_removed', 'edge_device', d.id::text,
          jsonb_build_object('device', d.device_name, 'version', d.app_version));
  delete from public.video_sources where edge_device_id = d.id;
  delete from public.edge_devices where id = d.id;
end $$;

-- A licence/client record in the portal (an installed on-prem file keeps working until it expires).
create or replace function public.admin_remove_client_license(target_license uuid)
returns void language plpgsql security definer set search_path to '' as $$
declare l record;
begin
  if not private.is_super_admin() then raise exception 'not authorized'; end if;
  select id, organization_id, client_name, edition, license_id into l from public.client_licenses where id = target_license;
  if l.id is null then raise exception 'Record not found'; end if;
  insert into public.audit_logs (organization_id, actor_user_id, action, target_type, target_id, metadata)
  values (l.organization_id, auth.uid(), 'license_record_removed', 'client_license', l.id::text,
          jsonb_build_object('client', l.client_name, 'edition', l.edition, 'license_id', l.license_id));
  delete from public.client_licenses where id = l.id;
end $$;

-- An online client account with everything under it (PCs, cameras, subscription record, history).
-- Refused while a paid Stripe subscription exists, and for the admin's own account.
create or replace function public.admin_remove_organization(target_org uuid)
returns void language plpgsql security definer set search_path to '' as $$
declare o record;
begin
  if not private.is_super_admin() then raise exception 'not authorized'; end if;
  select id, name, plan_code into o from public.organizations where id = target_org;
  if o.id is null then raise exception 'Client not found'; end if;
  if exists (select 1 from public.organization_members where organization_id = o.id and user_id = auth.uid()) then
    raise exception 'This is your own account, so it cannot be removed here.';
  end if;
  if exists (select 1 from public.subscriptions where organization_id = o.id and provider_subscription_id is not null
             and coalesce(status, '') not in ('canceled', 'cancelled', 'incomplete_expired')) then
    raise exception 'This client still has a Stripe subscription. Cancel it in Stripe first, then remove the client.';
  end if;
  insert into public.audit_logs (organization_id, actor_user_id, action, target_type, target_id, metadata)
  values (null, auth.uid(), 'client_removed', 'organization', o.id::text, jsonb_build_object('client', o.name, 'plan', o.plan_code));
  delete from public.client_licenses where organization_id = o.id;
  delete from public.organizations where id = o.id;  -- members, sites, PCs, cameras, subscription, history cascade
end $$;

revoke execute on function public.admin_remove_device(uuid), public.admin_remove_client_license(uuid), public.admin_remove_organization(uuid) from public, anon;
grant execute on function public.admin_remove_device(uuid), public.admin_remove_client_license(uuid), public.admin_remove_organization(uuid) to authenticated;
