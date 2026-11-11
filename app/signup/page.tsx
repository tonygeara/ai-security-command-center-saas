// Accounts are set up by the provider, not self-service. Old /signup links go to the demo request form.
import {redirect} from "next/navigation";
export default function Signup(){ redirect("/#request-demo"); }
