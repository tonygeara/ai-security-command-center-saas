-- New organizations start on plan_code 'trial', but no 'trial' plan existed, so
-- edge-agent-control returned no features and trial customers had everything locked.
-- Trial mirrors Pro. Not purchasable (active = false); tune it in the admin console.
insert into public.plans (code, name, monthly_price_cad, active)
values ('trial', 'Trial', 0, false)
on conflict (code) do nothing;

insert into public.plan_features (plan_code, feature_key, enabled, limit_value)
select 'trial', feature_key, enabled, limit_value
from public.plan_features
where plan_code = 'pro'
on conflict (plan_code, feature_key) do nothing;
