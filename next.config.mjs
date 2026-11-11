// The admin portal's "latest version" (installer links, out-of-date PCs) is the Windows app's own
// APP_VERSION, read at build time, so it moves with every release without anyone editing it.
import {readFileSync} from "node:fs";

let edgeVersion = "";
try {
  edgeVersion = (readFileSync(new URL("./edge/app/launcher.pyw", import.meta.url), "utf8").match(/^APP_VERSION = '(?:V)?([\d.]+)'/m) || [])[1] || "";
} catch {}

/** @type {import('next').NextConfig} */
export default {env: {EDGE_APP_VERSION: edgeVersion}};
