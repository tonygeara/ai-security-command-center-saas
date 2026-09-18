# Edge entitlement integration

The Windows Edge Agent should authenticate as its assigned customer/device identity and periodically retrieve its effective feature entitlement from the SaaS backend. Drone AI must be enforced in the Edge Agent itself, not only hidden in the web UI.

For the first customer-authenticated integration, call the Supabase RPC get_my_feature with target_feature = drone_ai. When enabled is false, the Edge Agent must stop/disable Drone AI processing. Do not embed a Supabase service-role key in the Windows application.

Next production hardening step: dedicated device credentials and a device-scoped entitlement endpoint so the Windows service does not depend on an interactive customer login.
