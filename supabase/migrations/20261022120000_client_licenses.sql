-- Client records and licences for both editions, managed from /admin/licenses.
--   onprem: offline .lic file signed by the issue-onprem-license function (document stored here)
--   saas:   portal account (organization); cameras/drones are applied as that client's limits
create table if not exists public.client_licenses (
  id uuid primary key default gen_random_uuid(),
  edition text not null check (edition in ('onprem', 'saas')),
  client_name text not null check (length(trim(client_name)) > 0),
  company text,
  location text,
  address text,
  contact_name text,
  phone text,
  email text,
  notes text,
  price numeric(12, 2),
  currency text not null default 'USD',
  billing_period text check (billing_period in ('one-time', 'monthly', 'yearly')),
  next_payment_date date,
  payment_status text check (payment_status in ('paid', 'pending', 'overdue')),
  organization_id uuid references public.organizations(id) on delete set null,
  machine_id text,
  plan text,
  cameras integer not null default 1 check (cameras >= 1),
  drones integer not null default 1 check (drones >= 0),
  features text[] not null default '{}',
  issued_on date,
  expires_on date,
  status text not null default 'active' check (status in ('active', 'revoked')),
  license_id uuid,
  license_document jsonb,
  created_by uuid default auth.uid(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists client_licenses_expires_idx on public.client_licenses (expires_on);
create index if not exists client_licenses_org_idx on public.client_licenses (organization_id);

alter table public.client_licenses enable row level security;

create policy client_licenses_superadmin_select on public.client_licenses
  for select using (private.is_super_admin());
create policy client_licenses_superadmin_insert on public.client_licenses
  for insert with check (private.is_super_admin());
create policy client_licenses_superadmin_update on public.client_licenses
  for update using (private.is_super_admin()) with check (private.is_super_admin());
create policy client_licenses_superadmin_delete on public.client_licenses
  for delete using (private.is_super_admin());

create or replace function public.touch_client_licenses()
returns trigger language plpgsql set search_path to '' as $$
begin
  new.updated_at := now();
  return new;
end $$;

drop trigger if exists client_licenses_touch on public.client_licenses;
create trigger client_licenses_touch before update on public.client_licenses
  for each row execute function public.touch_client_licenses();
