-- Super admin controls in the admin portal: rename a client, rename / switch off / switch on a client's PC,
-- switch a camera or drone off or on. Each is recorded in the activity log. A switched-off PC is refused
-- by edge-sync, edge-agent-control and edge-source-control until it is switched on again.

create or replace function public.admin_rename_organization(target_org uuid, new_name text)
returns void language plpgsql security definer set search_path to '' as $$
declare old text; n text := trim(coalesce(new_name, ''));
begin
  if not private.is_super_admin() then raise exception 'not authorized'; end if;
  if length(n) < 2 or length(n) > 120 then raise exception 'Enter a name of 2 to 120 characters.'; end if;
  select name into old from public.organizations where id = target_org;
  if old is null then raise exception 'Client not found'; end if;
  update public.organizations set name = n where id = target_org;
  update public.client_licenses set client_name = n where organization_id = target_org and client_name = old;
  insert into public.audit_logs (organization_id, actor_user_id, action, target_type, target_id, metadata)
  values (target_org, auth.uid(), 'client_renamed', 'organization', target_org::text, jsonb_build_object('from', old, 'to', n));
end $$;

create or replace function public.admin_update_device(target_device uuid, new_name text default null, enabled boolean default null)
returns void language plpgsql security definer set search_path to '' as $$
declare d record; n text := nullif(trim(coalesce(new_name, '')), '');
begin
  if not private.is_super_admin() then raise exception 'not authorized'; end if;
  select id, organization_id, device_name, status into d from public.edge_devices where id = target_device;
  if d.id is null then raise exception 'PC not found'; end if;
  if n is not null and length(n) > 80 then raise exception 'PC name is too long.'; end if;
  update public.edge_devices set
    device_name = coalesce(n, device_name),
    status = case when enabled is false then 'disabled' when enabled is true and status = 'disabled' then 'offline' else status end
  where id = d.id;
  insert into public.audit_logs (organization_id, actor_user_id, action, target_type, target_id, metadata)
  values (d.organization_id, auth.uid(),
          case when enabled is false then 'pc_disabled' when enabled is true then 'pc_enabled' else 'pc_renamed' end,
          'edge_device', d.id::text, jsonb_build_object('device', coalesce(n, d.device_name), 'from', case when n is not null then d.device_name end));
end $$;

create or replace function public.admin_set_source_enabled(target_source uuid, enabled boolean)
returns void language plpgsql security definer set search_path to '' as $$
declare s record;
begin
  if not private.is_super_admin() then raise exception 'not authorized'; end if;
  select id, organization_id, name, source_type into s from public.video_sources where id = target_source;
  if s.id is null then raise exception 'Camera or drone not found'; end if;
  update public.video_sources set enabled = admin_set_source_enabled.enabled where id = s.id;
  insert into public.audit_logs (organization_id, actor_user_id, action, target_type, target_id, metadata)
  values (s.organization_id, auth.uid(), case when enabled then 'source_enabled' else 'source_disabled' end, 'video_source', s.id::text,
          jsonb_build_object('name', s.name, 'type', s.source_type));
end $$;

revoke execute on function public.admin_rename_organization(uuid, text) from public, anon;
revoke execute on function public.admin_update_device(uuid, text, boolean) from public, anon;
revoke execute on function public.admin_set_source_enabled(uuid, boolean) from public, anon;
grant execute on function public.admin_rename_organization(uuid, text) to authenticated;
grant execute on function public.admin_update_device(uuid, text, boolean) to authenticated;
grant execute on function public.admin_set_source_enabled(uuid, boolean) to authenticated;
