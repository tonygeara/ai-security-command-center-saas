# ai-security-command-center-saas

## Roles
| Role | Where it is stored | Can do |
|---|---|---|
| Super admin | `super_admins` | Everything for every client: New online client (with its admin), any user's role/password/removal, PCs, cameras, sites, licences. |
| Admin | `organization_members.role` = `owner`/`admin` | Their own company: add/remove Viewers and Editors, reset their passwords, pair and remove PCs, billing. Limited by the licence's **Portal users (max)** and blocked while the account is suspended or the licence is revoked/expired. |
| Editor | `member` | Change cameras, sites and PC names. No users, billing or pairing. |
| Viewer | `viewer` | See everything in their company; change nothing. |

Users are created, changed and removed only by the `manage-users` function (`supabase/functions/manage-users`), which
holds these rules and writes every change to `audit_logs`. New users get a temporary password, shown once to whoever
made it; they must choose their own at first sign-in (`/account/password`). Database rules:
`supabase/migrations/20261108130000_roles_and_users.sql`.

Self-signup is off: only the super admin creates companies (Admin → Clients → + New online client), and
`create_my_organization` can no longer be called (`supabase/migrations/20261108140000_disable_self_signup.sql`).
`/signup` and `/onboarding` now explain that accounts come from the provider.

