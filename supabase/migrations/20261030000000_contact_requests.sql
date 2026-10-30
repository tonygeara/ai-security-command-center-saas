-- Enquiries sent from the public website's contact form.
-- Anyone (anon) can insert a request; only super admins can read or manage them.
create table if not exists public.contact_requests (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  name text not null check (char_length(name) between 1 and 120),
  email text not null check (char_length(email) between 3 and 200),
  phone text check (char_length(phone) <= 40),
  company text check (char_length(company) <= 160),
  property_type text check (char_length(property_type) <= 80),
  interest text check (char_length(interest) <= 80),
  message text not null check (char_length(message) between 1 and 5000),
  source_page text check (char_length(source_page) <= 200),
  email_sent boolean not null default false,
  status text not null default 'new' check (status in ('new', 'contacted', 'closed'))
);

alter table public.contact_requests enable row level security;

drop policy if exists "Anyone can submit a contact request" on public.contact_requests;
create policy "Anyone can submit a contact request" on public.contact_requests
  for insert to anon, authenticated
  with check (status = 'new');

drop policy if exists "Super admins read contact requests" on public.contact_requests;
create policy "Super admins read contact requests" on public.contact_requests
  for select to authenticated
  using (exists (select 1 from public.super_admins sa where sa.user_id = auth.uid()));

drop policy if exists "Super admins update contact requests" on public.contact_requests;
create policy "Super admins update contact requests" on public.contact_requests
  for update to authenticated
  using (exists (select 1 from public.super_admins sa where sa.user_id = auth.uid()))
  with check (exists (select 1 from public.super_admins sa where sa.user_id = auth.uid()));

create index if not exists contact_requests_created_at_idx on public.contact_requests (created_at desc);
