-- Phone access: incidents and live pictures from the customer's Windows edge agent, shown in the portal.
-- The edge agent writes only through the edge-sync function (service role, authenticated by its device
-- token). Customers read their own organisation's rows; super admins read everything.

create table if not exists public.remote_incidents (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  device_id uuid not null references public.edge_devices(id) on delete cascade,
  local_id bigint not null,
  camera text not null default '',
  title text not null default '',
  level text not null default 'activity',
  severity smallint not null default 1,
  status text not null default 'open',
  started_at timestamptz not null,
  updated_at timestamptz not null,
  items jsonb not null default '[]',
  photo_path text,
  received_at timestamptz not null default now(),
  unique (device_id, local_id)
);
create index if not exists remote_incidents_org_updated_idx on public.remote_incidents (organization_id, updated_at desc);

create table if not exists public.remote_cameras (
  device_id uuid primary key references public.edge_devices(id) on delete cascade,
  organization_id uuid not null references public.organizations(id) on delete cascade,
  cameras text[] not null default '{}',
  updated_at timestamptz not null default now()
);

-- A phone asks for live pictures of one camera; the edge agent uploads a picture every few seconds
-- until active_until. The portal extends active_until while the viewer stays on the page.
create table if not exists public.live_requests (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  device_id uuid not null references public.edge_devices(id) on delete cascade,
  camera text not null check (length(camera) between 1 and 80),
  requested_by uuid not null default auth.uid() references auth.users(id) on delete cascade,
  requested_at timestamptz not null default now(),
  active_until timestamptz not null default now() + interval '2 minutes',
  last_frame_at timestamptz,
  frame_path text
);
create index if not exists live_requests_device_idx on public.live_requests (device_id, active_until desc);

alter table public.remote_incidents enable row level security;
alter table public.remote_cameras enable row level security;
alter table public.live_requests enable row level security;

create or replace function private.is_org_member(org uuid)
returns boolean language sql stable security definer set search_path to '' as $$
  select exists (select 1 from public.organization_members m where m.organization_id = org and m.user_id = auth.uid())
$$;
revoke execute on function private.is_org_member(uuid) from public, anon;
grant execute on function private.is_org_member(uuid) to authenticated;

create policy remote_incidents_select on public.remote_incidents
  for select using (private.is_org_member(organization_id) or private.is_super_admin());
create policy remote_cameras_select on public.remote_cameras
  for select using (private.is_org_member(organization_id) or private.is_super_admin());

create policy live_requests_select on public.live_requests
  for select using (private.is_org_member(organization_id) or private.is_super_admin());
-- Members ask for live pictures of a device in their own organisation (at most 2 minutes at a time).
create policy live_requests_insert on public.live_requests
  for insert with check (
    private.is_org_member(organization_id)
    and requested_by = auth.uid()
    and active_until <= now() + interval '2 minutes 5 seconds'
    and exists (select 1 from public.edge_devices d where d.id = device_id and d.organization_id = live_requests.organization_id));
-- ...and keep watching (extend their own request, again at most 2 minutes ahead).
create policy live_requests_update on public.live_requests
  for update using (requested_by = auth.uid() and private.is_org_member(organization_id))
  with check (requested_by = auth.uid() and active_until <= now() + interval '2 minutes 5 seconds');

-- Columns a phone may change on its own request: only active_until.
revoke update on public.live_requests from authenticated;
grant update (active_until) on public.live_requests to authenticated;

-- Pictures: private bucket, one folder per organisation (<org id>/...). Written by edge-sync only.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('edge-pictures', 'edge-pictures', false, 2097152, array['image/jpeg'])
on conflict (id) do nothing;

create policy edge_pictures_read on storage.objects
  for select using (
    bucket_id = 'edge-pictures'
    and ((storage.foldername(name))[1] in (select m.organization_id::text from public.organization_members m
                                            where m.user_id = auth.uid())
         or private.is_super_admin()));
