// Accounts are no longer self-service: the provider creates each company and its admin, and the admin
// adds their own users. This page stays at /signup so old links explain that instead of breaking.
export default function Signup(){
 return <main className="shell"><a className="brand authBrand" href="/">AI SECURITY COMMAND CENTRE</a><div className="card login-card"><p className="eyebrow">GET AN ACCOUNT</p><h1>Accounts are set up for you</h1>
  <p className="muted">Your provider sets up your company and its admin. Your admin then signs in and adds the rest of your team as Editors or Viewers.</p>
  <p className="muted">Already have an account? <a href="/login">Sign in</a></p></div></main>
}
