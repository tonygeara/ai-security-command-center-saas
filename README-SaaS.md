# AI Security Command Center SaaS

Initial Next.js portal foundation.

## Local setup
1. Copy .env.example to .env.local.
2. Add the Supabase publishable/anon key. Never commit service-role keys.
3. Run npm install.
4. Run npm run dev.

## Current backend
Supabase project ref: qfnxwuejfotofuxlyqjd (Canada Central).

The database already contains organizations, memberships, sites, edge devices, video sources, subscriptions, feature entitlements, audit logs, plans and plan features. Super-admin access is controlled server-side/RLS.

## Next
Authentication, protected Super Admin routes, customer management, entitlement controls, device enrollment and deployment.
