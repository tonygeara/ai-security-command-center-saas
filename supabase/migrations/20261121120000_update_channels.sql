-- Per-client update channels (admin portal → client → Updates). Which version each client's PCs install when their
-- Settings → Updates switch is on:
--   test    the newest published version, as soon as it's out
--   normal  the version the super admin approved (admin portal → Installers → Approved for Normal clients)
--   pinned  exactly pinned_version (a PC never downgrades by itself: an older pin just keeps it from updating)
-- The PC gets it from edge-agent-control ("updates": {"channel", "version"}).

alter table public.organizations add column if not exists update_channel text not null default 'normal'
  check (update_channel in ('normal', 'test', 'pinned'));
alter table public.organizations add column if not exists pinned_version text
  check (pinned_version is null or pinned_version ~ '^V[0-9]+\.[0-9]+\.[0-9]+$');

create table if not exists public.edge_release_policy (
  id integer primary key default 1 check (id = 1),
  approved_version text check (approved_version is null or approved_version ~ '^V[0-9]+\.[0-9]+\.[0-9]+$'),
  updated_at timestamptz not null default now(),
  updated_by uuid
);
alter table public.edge_release_policy enable row level security;
drop policy if exists "super admins read the release policy" on public.edge_release_policy;
create policy "super admins read the release policy" on public.edge_release_policy for select to authenticated
  using ((select private.is_super_admin()));
insert into public.edge_release_policy (id, approved_version) values (1, 'V11.13.0') on conflict (id) do nothing;

create or replace function public.set_update_channel(target_org uuid, target_channel text, target_version text default null)
returns void language plpgsql security definer set search_path to '' as $$
declare o record;
begin
  if not private.is_super_admin() then raise exception 'not authorized'; end if;
  if target_channel not in ('normal', 'test', 'pinned') then raise exception 'invalid channel'; end if;
  if target_channel = 'pinned' and (target_version is null or target_version !~ '^V[0-9]+\.[0-9]+\.[0-9]+$') then
    raise exception 'Choose the version to pin'; end if;
  select id, name, update_channel, pinned_version into o from public.organizations where id = target_org for update;
  if o.id is null then raise exception 'Client not found'; end if;
  update public.organizations set update_channel = target_channel,
         pinned_version = case when target_channel = 'pinned' then target_version else null end, updated_at = now()
   where id = o.id;
  insert into public.audit_logs (organization_id, actor_user_id, action, target_type, target_id, metadata)
  values (o.id, auth.uid(), 'update_channel_changed', 'organization', o.id::text,
          jsonb_build_object('client', o.name, 'channel', target_channel, 'version', target_version,
                             'previous_channel', o.update_channel, 'previous_version', o.pinned_version));
end $$;
revoke execute on function public.set_update_channel(uuid, text, text) from public, anon;
grant execute on function public.set_update_channel(uuid, text, text) to authenticated;

create or replace function public.approve_edge_version(target_version text)
returns void language plpgsql security definer set search_path to '' as $$
declare prev text;
begin
  if not private.is_super_admin() then raise exception 'not authorized'; end if;
  if target_version is null or target_version !~ '^V[0-9]+\.[0-9]+\.[0-9]+$' then raise exception 'invalid version'; end if;
  select approved_version into prev from public.edge_release_policy where id = 1;
  insert into public.edge_release_policy (id, approved_version, updated_at, updated_by) values (1, target_version, now(), auth.uid())
  on conflict (id) do update set approved_version = excluded.approved_version, updated_at = now(), updated_by = auth.uid();
  insert into public.audit_logs (organization_id, actor_user_id, action, target_type, target_id, metadata)
  values (null, auth.uid(), 'edge_version_approved', 'edge_release', target_version,
          jsonb_build_object('version', target_version, 'previous', prev));
end $$;
revoke execute on function public.approve_edge_version(text) from public, anon;
grant execute on function public.approve_edge_version(text) to authenticated;

-- doumith tries every new version first.
update public.organizations set update_channel = 'test' where id = '8f2b52b8-3993-4f33-bc2f-126149a2624e';
