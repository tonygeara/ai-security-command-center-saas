# Product edition. build_onprem.ps1 writes the on-prem values into its build copy;
# this file in the source tree always stays the SaaS edition.
EDITION = "saas"            # "saas" (cloud pairing + subscription) or "onprem" (offline license file)
PRODUCT_NAME = "AI Security Command Center"
BRAND_TOP = "AI SECURITY"
BRAND_SUB = "COMMAND CENTER"
BRAND_FLAG = ""                       # optional flag beside BRAND_SUB, e.g. "lb"
DATA_DIR_NAME = "AI-Security-System"   # folder under %LOCALAPPDATA% for cameras, faces, events, license
