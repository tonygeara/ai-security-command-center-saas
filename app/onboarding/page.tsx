// Shown to a signed-in user who belongs to no company. Companies are created only by the provider now.
export default function Onboarding(){
 return <main className="shell"><div className="brand">AI SECURITY COMMAND CENTER</div><div className="card login-card"><h1>No company yet</h1>
  <p className="muted">Your account isn&apos;t part of a company. Ask your company&apos;s admin to add you, or contact your provider to set up your company.</p>
  <p className="muted"><a href="/login">Back to sign in</a></p></div></main>
}
