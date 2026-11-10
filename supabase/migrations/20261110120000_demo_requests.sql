-- Demo requests from the website's "Request a demo" form. Only the super admin reads them (Admin → Demo
-- requests). The website posts to the demo-request edge function, which calls submit_demo_request with the
-- service role; the function checks the fields and limits how often the same address (or the whole site)
-- can submit, so the form can't be used to flood the table. The public can't call it directly.

create table if not exists public.demo_requests (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  full_name text not null check (length(full_name) between 2 and 120),
  email text not null check (length(email) between 5 and 200 and email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  company text check (length(company) <= 160),
  phone text check (length(phone) <= 40),
  country text check (length(country) <= 80),
  sites text check (length(sites) <= 40),
  message text check (length(message) <= 2000),
  source_ip text check (length(source_ip) <= 64),
  status text not null default 'new' check (status in ('new', 'contacted', 'closed')),
  emailed boolean not null default false
);
create index if not exists demo_requests_created_idx on public.demo_requests (created_at desc);
create index if not exists demo_requests_email_idx on public.demo_requests (lower(email), created_at desc);

alter table public.demo_requests enable row level security;
revoke all on public.demo_requests from anon, authenticated;
grant select, update (status), delete on public.demo_requests to authenticated;

create policy demo_requests_superadmin_select on public.demo_requests for select to authenticated using (private.is_super_admin());
create policy demo_requests_superadmin_update on public.demo_requests for update to authenticated
  using (private.is_super_admin()) with check (private.is_super_admin());
create policy demo_requests_superadmin_delete on public.demo_requests for delete to authenticated using (private.is_super_admin());

-- The only way in for the public: checked, limited (3 per address per day, 200 per day in all).
create or replace function public.submit_demo_request(full_name text, email text, company text default null, phone text default null,
                                                      country text default null, sites text default null, message text default null,
                                                      source_ip text default null)
returns uuid language plpgsql security definer set search_path to '' as $$
declare new_id uuid; e text := lower(trim(coalesce(email, '')));
begin
  if (select count(*) from public.demo_requests r where lower(r.email) = e and r.created_at > now() - interval '1 day') >= 3 then
    raise exception 'You have already sent a request today. We will be in touch soon.' using errcode = 'P0001';
  end if;
  if (select count(*) from public.demo_requests r where r.created_at > now() - interval '1 day') >= 200 then
    raise exception 'Too many requests right now. Please try again tomorrow.' using errcode = 'P0001';
  end if;
  insert into public.demo_requests (full_name, email, company, phone, country, sites, message, source_ip)
  values (trim(full_name), e, nullif(trim(company), ''), nullif(trim(phone), ''), nullif(trim(country), ''),
          nullif(trim(sites), ''), nullif(trim(message), ''), nullif(trim(source_ip), ''))
  returning id into new_id;
  return new_id;
end $$;
revoke execute on function public.submit_demo_request(text, text, text, text, text, text, text, text) from public, anon, authenticated;
grant execute on function public.submit_demo_request(text, text, text, text, text, text, text, text) to service_role;
