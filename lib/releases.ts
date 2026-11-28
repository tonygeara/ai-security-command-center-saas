// Published Windows versions (GitHub releases edge-v<version>), newest first, for the update channel pickers.
// Used by the server (lib/admin.ts) and, when the server got nothing, by the admin's own browser (useEdgeVersions):
// GitHub allows 60 unsigned requests an hour per address, and the website's servers share their addresses with other
// sites, so the server's request can be refused while the admin's browser still gets the list.
export const RELEASES_API = "https://api.github.com/repos/tonygeara/ai-security-command-center-saas/releases?per_page=50";

export function parseEdgeVersions(rows: unknown): string[] {
  if (!Array.isArray(rows)) return [];
  const vs = (rows as {tag_name?: string; draft?: boolean}[]).filter(x => x && !x.draft)
    .map(x => /^edge-v(\d+)\.(\d+)\.(\d+)$/.exec(x.tag_name || "")).filter((m): m is RegExpExecArray => !!m)
    .map(m => [Number(m[1]), Number(m[2]), Number(m[3])]);
  vs.sort((a, b) => b[0] - a[0] || b[1] - a[1] || b[2] - a[2]);
  return vs.map(v => `V${v.join(".")}`);
}
