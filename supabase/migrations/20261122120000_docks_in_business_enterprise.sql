-- DJI Docks in the plans: Business includes 1 dock, Enterprise has no dock limit; Home, Pro and Trial don't include
-- docks. A client's own setting (admin portal → client → Feature access, licence form "DJI Docks (max)") still wins
-- over the plan, e.g. doumith (Home) keeps its 1 dock.
insert into public.plan_features (plan_code, feature_key, enabled, limit_value) values
  ('business', 'drone_dock', true, 1),
  ('enterprise', 'drone_dock', true, null),
  ('home', 'drone_dock', false, 0),
  ('pro', 'drone_dock', false, 0),
  ('trial', 'drone_dock', false, 0)
on conflict (plan_code, feature_key) do update set enabled = excluded.enabled, limit_value = excluded.limit_value;
