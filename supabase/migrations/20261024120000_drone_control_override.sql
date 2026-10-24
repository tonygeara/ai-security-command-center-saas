-- Per-client "Fly drone from PC" for online (SaaS) clients, like on-prem licences.
create or replace function public.set_feature_override(target_org uuid, target_feature text, target_enabled boolean, target_limit integer default null)
returns void
language plpgsql
set search_path to ''
as $function$
begin
 if not private.is_super_admin() then raise exception 'not authorized'; end if;
 if target_feature not in ('camera_ai','face_ai','lpr','drone_live','drone_ai','drone_tracking','drone_control') then raise exception 'invalid feature'; end if;
 insert into public.feature_entitlements(organization_id,feature_key,enabled,limit_value,source)
 values(target_org,target_feature,target_enabled,target_limit,'manual')
 on conflict(organization_id,feature_key) do update set enabled=excluded.enabled,limit_value=excluded.limit_value,source='manual',updated_at=now();
 insert into public.audit_logs(organization_id,actor_user_id,action,target_type,target_id,metadata)
 values(target_org,(select auth.uid()),'feature_override_changed','feature_entitlement',target_feature,jsonb_build_object('feature',target_feature,'enabled',target_enabled,'limit_value',target_limit));
end $function$;
