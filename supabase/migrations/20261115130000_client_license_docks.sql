-- How many DJI Docks a client's licence allows (admin portal → licence form → "DJI Docks (max)").
-- Online clients: also saved as the limit of their drone_dock feature switch. On-prem: in the signed file (limits.docks).
alter table public.client_licenses add column if not exists docks integer not null default 0
  check (docks between 0 and 50);
