# Windows Edge Agent cloud control

Production endpoint: `https://qfnxwuejfotofuxlyqjd.supabase.co/functions/v1/edge-agent-control`

The Edge Agent authenticates with a per-device random token sent as `x-device-token`. Never embed a Supabase service-role key in the Windows app.

On startup and periodically (recommended every 30-60 seconds), POST to the endpoint. The response contains the device id, organization status and effective feature map.

Enforcement rule: if the organization is not active, disable subscription-controlled AI. For Drone AI, read `features.drone_ai.enabled`. When false, stop Drone AI inference/tracking and prevent it from starting. When true, allow the locally configured Drone AI pipeline.

A successful poll updates `edge_devices.last_seen_at` and status to `online`, powering the Super Admin device-health view.

Device enrollment tokens must be generated locally with a cryptographically secure random generator. Store only the SHA-256 hash in Supabase; store the raw token only on the enrolled Windows device.
