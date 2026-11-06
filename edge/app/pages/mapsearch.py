"""Search by address and "Locate me" on every map (served as /mapsearch.js; needs Leaflet first).

addMapSearch(map) adds a box at the map's top left: type an address, place or "lat, lon" and pick a result;
◎ moves the map to where this computer is (the browser's location), or to the site if that is not available.
Addresses are looked up through the dashboard (/api/geocode, OpenStreetMap's Nominatim), so it needs internet;
coordinates work offline.
"""
JS = r"""
(function(){
  const css = `.msr{display:flex;gap:4px;background:rgba(3,16,26,.92);border:1px solid #155879;border-radius:5px;padding:4px;box-shadow:0 2px 8px rgba(0,0,0,.5)}
.msr input{width:220px;max-width:46vw;background:#020a10;color:#d9efff;border:1px solid #155879;border-radius:3px;padding:6px 8px;font:12px Arial;outline:none}
.msr input:focus{border-color:#36cfff}
.msr button{background:#05131d;color:#5bd9ff;border:1px solid #155879;border-radius:3px;min-width:30px;cursor:pointer;font:bold 14px Arial}
.msr button:hover{color:#fff;border-color:#36cfff}
.msr-list{margin-top:4px;background:rgba(3,16,26,.96);border:1px solid #155879;border-radius:5px;max-width:300px;overflow:hidden}
.msr-list div{padding:7px 9px;color:#cfeeff;font:12px Arial;cursor:pointer;border-bottom:1px solid #123447}
.msr-list div:last-child{border-bottom:0}.msr-list div:hover{background:rgba(37,199,255,.15)}
.msr-list .msr-note{color:#8ba9b8;cursor:default}.msr-list .msr-note:hover{background:none}`;
  if (!document.getElementById('msr-css')) { const st = document.createElement('style'); st.id = 'msr-css'; st.textContent = css; document.head.appendChild(st); }
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);

  // The place being looked at, shared by every map on this PC (flat map, 3D MAP, 4D LIVE, the other tabs): set by a
  // search, Locate me, or moving a map, so switching views stays on the same spot.
  const KEY = 'map-focus';
  window.mapFocus = {
    get(){ try { const f = JSON.parse(localStorage.getItem(KEY)); return f && isFinite(f.lat) && isFinite(f.lon) ? f : null; } catch (e) { return null; } },
    set(lat, lon, zoom){ try { localStorage.setItem(KEY, JSON.stringify({lat: +lat, lon: +lon, zoom: zoom || 17, at: Date.now()})); } catch (e) {} },
    clear(){ try { localStorage.removeItem(KEY); } catch (e) {} },
  };

  // Returns true when the map was moved to the saved place (the page then skips its own first centring).
  window.addMapSearch = function(map, opts){
    if (!map || typeof L === 'undefined' || map._msr) return false;
    map._msr = true;
    opts = opts || {};
    let mark = null;
    const show = (lat, lon, label, zoom) => {
      map.setView([lat, lon], zoom || Math.max(map.getZoom(), 17));
      mapFocus.set(lat, lon, map.getZoom());
      if (mark) map.removeLayer(mark);
      mark = L.circleMarker([lat, lon], {radius: 9, color: '#fff', weight: 2, fillColor: '#25c7ff', fillOpacity: .9}).addTo(map);
      if (label) mark.bindTooltip(esc(label), {permanent: false}).openTooltip();
      setTimeout(() => { if (mark) { map.removeLayer(mark); mark = null; } }, 20000);
    };
    const Ctl = L.Control.extend({options: {position: opts.position || 'topleft'}, onAdd(){
      const box = L.DomUtil.create('div');
      box.innerHTML = '<div class="msr"><input type="search" placeholder="Search address or lat, lon" aria-label="Search the map">' +
        '<button type="button" title="Search">⌕</button><button type="button" title="Locate me">◎</button></div><div class="msr-list" hidden></div>';
      L.DomEvent.disableClickPropagation(box); L.DomEvent.disableScrollPropagation(box);
      const input = box.querySelector('input'), [go, me] = box.querySelectorAll('button'), list = box.querySelector('.msr-list');
      const note = t => { list.hidden = false; list.innerHTML = `<div class="msr-note">${esc(t)}</div>`; };
      const search = async () => {
        const q = input.value.trim();
        if (q.length < 3) { note('Type at least 3 letters, or coordinates like 33.89, 35.50'); return; }
        const m = q.match(/^\s*(-?\d{1,2}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)\s*$/);
        if (m && Math.abs(+m[1]) <= 90 && Math.abs(+m[2]) <= 180) { list.hidden = true; show(+m[1], +m[2], q, 18); return; }
        note('Searching…');
        let d;
        try { d = await fetch('/api/geocode?q=' + encodeURIComponent(q)).then(r => r.json()); }
        catch (e) { note('No answer from the dashboard.'); return; }
        if (!d.ok) { note(d.error || 'Search failed.'); return; }
        if (!d.results.length) { note('Nothing found. Try a street and town, or coordinates.'); return; }
        list.innerHTML = d.results.map((r, i) => `<div data-i="${i}">${esc(r.name)}</div>`).join('');
        list.querySelectorAll('[data-i]').forEach(el => el.onclick = () => {
          const r = d.results[+el.dataset.i]; list.hidden = true; input.value = r.name; show(r.lat, r.lon, r.name, 18);
        });
        if (d.results.length === 1) list.querySelector('[data-i]').click();
      };
      go.onclick = search;
      input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); search(); } if (e.key === 'Escape') list.hidden = true; });
      me.onclick = () => {
        const fallback = async why => {
          try {
            const d = await fetch('/api/safety', {cache: 'no-store'}).then(r => r.json());
            const p = d && d.site && d.site.pos;
            if (p) { show(p[0], p[1], 'Site (' + (d.site.from || 'saved position') + ')', 17); note(why + ' Showing the site instead.'); setTimeout(() => list.hidden = true, 4000); return; }
          } catch (e) {}
          note(why);
        };
        if (!navigator.geolocation) { fallback('This browser can\'t give a location.'); return; }
        note('Finding where you are…');
        navigator.geolocation.getCurrentPosition(p => {
          list.hidden = true;
          show(p.coords.latitude, p.coords.longitude, `You are here (±${Math.round(p.coords.accuracy)} m)`, p.coords.accuracy > 500 ? 15 : 18);
        }, err => fallback(err.code === 1 ? 'Location is blocked for this page (allow it in the browser\'s address bar).' : 'This computer could not find its location.'),
        {enableHighAccuracy: true, timeout: 10000, maximumAge: 60000});
      };
      return box;
    }});
    new Ctl().addTo(map);
    const saved = mapFocus.get();
    if (saved && opts.restore !== false) map.setView([saved.lat, saved.lon], saved.zoom || map.getZoom());
    // Moving the map by hand keeps the shared place up to date (not the page's own automatic moves).
    let byUser = false;
    map.on('dragstart zoomstart', e => { if (e.originalEvent || map._msrUser) byUser = true; });
    map.getContainer().addEventListener('pointerdown', () => { map._msrUser = true; });
    map.getContainer().addEventListener('wheel', () => { map._msrUser = true; }, {passive: true});
    map.on('moveend', () => { if (byUser || map._msrUser) { const c = map.getCenter(); mapFocus.set(c.lat, c.lng, map.getZoom()); } byUser = false; map._msrUser = false; });
    return !!(saved && opts.restore !== false);
  };
})();
"""
