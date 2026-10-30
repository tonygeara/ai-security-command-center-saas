export function DronePanel() {
  return (
      <div className="dPanel" aria-hidden="true">
        <div className="screenTop"><i/> PATROL ACTIVE <span>NIGHT ROUTE · 02:00</span></div>
        <div className="dMap">
          <svg viewBox="0 0 400 260" preserveAspectRatio="none">
            <defs>
              <pattern id="grid" width="26" height="26" patternUnits="userSpaceOnUse">
                <path d="M26 0H0V26" fill="none" stroke="#14303f" strokeWidth="1"/>
              </pattern>
            </defs>
            <rect width="400" height="260" fill="url(#grid)"/>
            <rect x="150" y="95" width="90" height="60" rx="4" fill="#0f2534" stroke="#244a5e"/>
            <path d="M40 220 L95 60 L300 45 L355 190 L190 230 Z" fill="none" stroke="#37d4ff" strokeWidth="2.5" strokeDasharray="7 6" className="dRoute"/>
            {[[40,220,"H"],[95,60,"1"],[300,45,"2"],[355,190,"3"],[190,230,"4"]].map(([x,y,l]) => (
              <g key={String(l)}>
                <circle cx={Number(x)} cy={Number(y)} r="11" fill={l==="H"?"#54ef9c":"#0b6fa8"} stroke="#9fe9ff" strokeWidth="1.5"/>
                <text x={Number(x)} y={Number(y)+4} textAnchor="middle" fontSize="11" fontWeight="700" fill="#061019">{l}</text>
              </g>
            ))}
            <g className="dDrone">
              <circle cx="300" cy="45" r="18" fill="#37d4ff22" stroke="#37d4ff"/>
              <path d="M292 37l16 16M308 37l-16 16" stroke="#eaf6ff" strokeWidth="2.5" strokeLinecap="round"/>
            </g>
          </svg>
          <div className="dHud">
            <span>ALT 30 m</span><span>SPD 6 m/s</span><span>BATT 74%</span>
          </div>
        </div>
        <div className="dFeedRow">
          <div className="dFeed">
            <strong>DRONE CAM · STOP 2</strong>
            <div className="dFace"/>
            <span className="box">UNKNOWN PERSON</span>
          </div>
          <div className="feed events">
            <strong>PATROL LOG</strong>
            <p>Unknown face at stop 2 <small>now</small></p>
            <p>Vehicle at gate <small>3m</small></p>
            <p>Patrol started <small>6m</small></p>
          </div>
        </div>
      </div>
  );
}
