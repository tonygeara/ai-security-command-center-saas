-- Admin portal: super admins can read the activity log, and every client/licence change is logged.
create policy audit_logs_select_superadmin on public.audit_logs
  for select using (private.is_super_admin());

create or replace function public.log_client_license_change()
returns trigger language plpgsql security definer set search_path to '' as $$
declare
  act text;
begin
  if tg_op = 'INSERT' then
    act := case when new.edition = 'onprem' then 'license_issued' else 'client_added' end;
  elsif new.status = 'revoked' and old.status is distinct from 'revoked' then
    act := 'license_revoked';
  elsif new.license_id is distinct from old.license_id then
    act := 'license_renewed';
  else
    act := 'client_updated';
  end if;
  insert into public.audit_logs (organization_id, actor_user_id, action, target_type, target_id, metadata)
  values (new.organization_id, auth.uid(), act, 'client_license', new.id::text,
          jsonb_build_object('client', new.client_name, 'edition', new.edition, 'cameras', new.cameras,
                             'drones', new.drones, 'expires_on', new.expires_on, 'license_id', new.license_id));
  return new;
end $$;

revoke execute on function public.log_client_license_change() from public, anon, authenticated;

drop trigger if exists client_licenses_audit on public.client_licenses;
create trigger client_licenses_audit after insert or update on public.client_licenses
  for each row execute function public.log_client_license_change();
