-- Every feature is now part of the plans (before, these six were on for every client unless switched off per client):
--   Home:       phone access, 4D incident replay
--   Pro/Trial:  + fly the drone from the PC
--   Business:   + camera-to-drone handoff, Smart patrol, drone-verified alarms
--   Enterprise: everything
-- A client's own Feature access setting still wins over its plan.
insert into public.plan_features (plan_code, feature_key, enabled, limit_value)
select p.plan_code, f.feature_key,
       case f.feature_key
         when 'phone_access' then true
         when 'incident_replay' then true
         when 'drone_control' then p.plan_code in ('pro', 'trial', 'business', 'enterprise')
         else p.plan_code in ('business', 'enterprise')   -- handoff, smart_patrol, verified_alarms
       end, null
from (values ('home'), ('pro'), ('trial'), ('business'), ('enterprise')) as p(plan_code)
cross join (values ('phone_access'), ('incident_replay'), ('drone_control'), ('handoff'), ('smart_patrol'), ('verified_alarms')) as f(feature_key)
on conflict (plan_code, feature_key) do update set enabled = excluded.enabled, limit_value = excluded.limit_value;
