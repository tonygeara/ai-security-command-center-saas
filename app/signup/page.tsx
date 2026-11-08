// Accounts are no longer self-service: the provider creates each company and its admin, and the admin
// adds their own users. This page stays at /signup so old links explain that instead of breaking.
export default function Signup(){
 return <main className="shell"><div className="brand">AI SECURITY COMMAND CENTER</div><div className="card login-card"><h1>Get an account</h1>
  <p className="muted">Accounts are set up for you by your provider. Once your company is set up, your admin gets a sign-in and can add the rest of your team.</p>
  <p className="muted">Already have an account? <a href="/login">Sign in</a></p></div></main>
}
