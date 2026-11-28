"use client";
import {useEffect, useState} from "react";
import {parseEdgeVersions, RELEASES_API} from "./releases";

// In the browser: the list the server sent, or (when it is empty) the list fetched from GitHub by the browser itself.
export function useEdgeVersions(initial: string[]): {versions: string[]; loading: boolean; failed: boolean} {
  const [versions, setVersions] = useState(initial), [loading, setLoading] = useState(!initial.length), [failed, setFailed] = useState(false);
  useEffect(() => {
    if (initial.length) return;
    let gone = false;
    fetch(RELEASES_API, {headers: {Accept: "application/vnd.github+json"}})
      .then(r => r.ok ? r.json() : Promise.reject(new Error(String(r.status))))
      .then(rows => { if (!gone) { const v = parseEdgeVersions(rows); setVersions(v); setFailed(!v.length); } })
      .catch(() => { if (!gone) setFailed(true); })
      .finally(() => { if (!gone) setLoading(false); });
    return () => { gone = true; };
  }, [initial]);
  return {versions, loading, failed};
}
