-- 1. The newer features can be switched on or off per client (admin portal → client → Feature access).
-- 2. Block / unblock a whole client in one step: account suspended (every feature off on their PCs), every
--    PC switched off (refused by the cloud), and every user of the company unable to sign in (super admins
--    are never blocked). Unblock reverses all three. Both recorded in the activity log.

create or replace function public.set_feature_override(target_org uuid, target_feature text, target_enabled boolean, target_limit integer default null)
returns void language plpgsql set search_path to '' as $$
begin
 if not private.is_super_admin() then raise exception 'not authorized'; end if;
 if target_feature not in ('camera_ai','face_ai','lpr','drone_live','drone_ai','drone_tracking','drone_control',
                           'handoff','smart_patrol','verified_alarms','incident_replay','phone_access') then
   raise exception 'invalid feature'; end if;
 insert into public.feature_entitlements(organization_id,feature_key,enabled,limit_value,source)
 values(target_org,target_feature,target_enabled,target_limit,'manual')
 on conflict(organization_id,feature_key) do update set enabled=excluded.enabled,limit_value=excluded.limit_value,source='manual',updated_at=now();
 insert into public.audit_logs(organization_id,actor_user_id,action,target_type,target_id,metadata)
 values(target_org,(select auth.uid()),'feature_override_changed','feature_entitlement',target_feature,
        jsonb_build_object('feature',target_feature,'enabled',target_enabled,'limit_value',target_limit));
end $$;

create or replace function public.admin_block_organization(target_org uuid, blocked boolean)
returns void language plpgsql security definer set search_path to '' as $$
declare o record; users_n int; pcs_n int;
begin
  if not private.is_super_admin() then raise exception 'not authorized'; end if;
  select id, name, status into o from public.organizations where id = target_org for update;
  if o.id is null then raise exception 'Client not found'; end if;
  update public.organizations set status = case when blocked then 'suspended' else 'active' end, updated_at = now() where id = o.id;
  update public.edge_devices set status = case when blocked then 'disabled' else 'offline' end
   where organization_id = o.id and (blocked or status = 'disabled');
  get diagnostics pcs_n = row_count;
  update auth.users u set banned_until = case when blocked then 'infinity'::timestamptz else null end
   where u.id in (select m.user_id from public.organization_members m where m.organization_id = o.id)
     and u.id not in (select s.user_id from public.super_admins s);
  get diagnostics users_n = row_count;
  insert into public.audit_logs (organization_id, actor_user_id, action, target_type, target_id, metadata)
  values (o.id, auth.uid(), case when blocked then 'client_blocked' else 'client_unblocked' end, 'organization', o.id::text,
          jsonb_build_object('client', o.name, 'previous_status', o.status, 'pcs', pcs_n, 'users', users_n));
end $$;
revoke execute on function public.admin_block_organization(uuid, boolean) from public, anon;
grant execute on function public.admin_block_organization(uuid, boolean) to authenticated;
