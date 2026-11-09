-- Self-signup is off: companies and their users are created only by the super admin (manage-users function).
-- Even someone who still gets an account cannot create a company for themselves.
revoke execute on function public.create_my_organization(text) from public, anon, authenticated;
