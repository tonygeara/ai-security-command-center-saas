CREATE OR REPLACE FUNCTION public.admin_manage_account(target_org uuid, target_status text, target_plan text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE paid_id text; previous_plan text; previous_status text;
BEGIN
 IF NOT private.is_super_admin() THEN RAISE EXCEPTION 'not authorized' USING ERRCODE='42501'; END IF;
 IF target_status NOT IN ('active','trial','suspended','cancelled') OR target_status IS NULL THEN RAISE EXCEPTION 'invalid account status'; END IF;
 SELECT plan_code,status INTO previous_plan,previous_status FROM public.organizations WHERE id=target_org FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'organization not found'; END IF;
 SELECT provider_subscription_id INTO paid_id FROM public.subscriptions WHERE organization_id=target_org FOR UPDATE;
 IF target_plan IS NOT NULL THEN
  IF paid_id IS NOT NULL THEN RAISE EXCEPTION 'Manage paid subscription plans through Stripe billing'; END IF;
  IF target_plan <> 'trial' AND NOT EXISTS(SELECT 1 FROM public.plans WHERE code=target_plan AND active) THEN RAISE EXCEPTION 'invalid plan'; END IF;
  UPDATE public.organizations SET plan_code=target_plan,updated_at=now() WHERE id=target_org;
  INSERT INTO public.subscriptions(organization_id,provider,plan_code,status)
   VALUES(target_org,'manual',target_plan,CASE WHEN target_status='cancelled' THEN 'canceled' ELSE target_status END)
  ON CONFLICT(organization_id) DO UPDATE SET plan_code=EXCLUDED.plan_code,status=EXCLUDED.status,updated_at=now();
 END IF;
 UPDATE public.organizations SET status=target_status,updated_at=now() WHERE id=target_org;
 INSERT INTO public.audit_logs(organization_id,actor_user_id,action,target_type,target_id,metadata)
 VALUES(target_org,auth.uid(),'admin_account_updated','organization',target_org::text,
 jsonb_build_object('previous_plan',previous_plan,'plan',coalesce(target_plan,previous_plan),'previous_status',previous_status,'status',target_status));
END $$;
REVOKE ALL ON FUNCTION public.admin_manage_account(uuid,text,text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.admin_manage_account(uuid,text,text) TO authenticated;

