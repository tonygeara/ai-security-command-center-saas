"""A route as a DJI flight plan (WPML in a KMZ file), for a dock's drone to fly on its own (DJI Cloud API, Phase 3).

The KMZ holds wpmz/template.kml (the mission settings) and wpmz/waylines.wpml (what the drone executes). Heights are
metres above the take-off point (the dock). The drone returns to the dock at the end, and also when it loses the link.
Detours round no-fly zones are added as extra waypoints without a pause or photo.

Format: DJI WPML 1.0.x as published with the Cloud API. Check against a real dock before relying on it: the dock
refuses a file it doesn't understand (flighttask_prepare fails), it never flies a misread one.
"""
import hashlib
import io
import math
import time
import zipfile

WPML_NS = "http://www.dji.com/wpmz/1.0.2"
MIN_ALT, MAX_ALT = 20.0, 120.0      # m above the dock (20 m: clear of the dock's surroundings)
MIN_SPEED, MAX_SPEED = 1.0, 12.0    # m/s
RTH_ALT = 60.0                       # return-to-dock height, m above the dock (raised to the route height)
GIMBAL_PITCH = -45.0                 # looking down at 45° while patrolling


def _num(v):
    return f"{float(v):.6f}".rstrip("0").rstrip(".")


def distance_m(a, b):
    """Metres between two (lat, lon) points."""
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def plan_points(dock, stops, detour=None, loop=False):
    """The waypoints to fly: [{"lat", "lon", "stop": bool}], with detours (detour(a, b) -> [(lat, lon)] or None) between
    the dock, the stops and back. Raises ValueError when there is no way round a no-fly zone."""
    pts, prev = [], (dock[0], dock[1])
    legs = [(s["lat"], s["lon"]) for s in stops]
    for i, target in enumerate(legs):
        via = detour(prev, target) if detour else []
        if via is None:
            raise ValueError(f"There is no way round the no-fly zones to stop {i + 1}.")
        pts += [{"lat": q[0], "lon": q[1], "stop": False} for q in via]
        pts.append({"lat": target[0], "lon": target[1], "stop": True})
        prev = target
    if loop and len(legs) > 1:  # back to the first stop to close the loop (the drone then returns to the dock)
        via = detour(prev, legs[0]) if detour else []
        if via is None:
            raise ValueError("There is no way round the no-fly zones back to stop 1.")
        pts += [{"lat": q[0], "lon": q[1], "stop": False} for q in via]
        pts.append({"lat": legs[0][0], "lon": legs[0][1], "stop": False})
    back = detour(prev, (dock[0], dock[1])) if detour else []
    if back is None:
        raise ValueError("There is no way round the no-fly zones back to the dock.")
    pts += [{"lat": q[0], "lon": q[1], "stop": False} for q in back]  # the drone lands at the dock after the last one
    return pts


def build_kmz(points, alt, speed, pause_s=0.0, drone_enum=(100, 1), payload_enum=99, name="AI Security patrol", now=None):
    """KMZ bytes for these waypoints ([{"lat", "lon", "stop"}]): fly at alt (m above the dock) and speed (m/s), hover
    pause_s at each stop, gimbal at 45° down, return to the dock at the end and on lost link."""
    if not points:
        raise ValueError("The route has no stops.")
    alt = max(MIN_ALT, min(MAX_ALT, float(alt)))
    speed = max(MIN_SPEED, min(MAX_SPEED, float(speed)))
    rth = max(RTH_ALT, alt)
    ms = int((now or time.time()) * 1000)
    total = sum(distance_m((a["lat"], a["lon"]), (b["lat"], b["lon"])) for a, b in zip(points, points[1:]))
    duration = total / speed + pause_s * sum(1 for p in points if p["stop"])
    mission = f"""  <wpml:missionConfig>
    <wpml:flyToWaylineMode>safely</wpml:flyToWaylineMode>
    <wpml:finishAction>goHome</wpml:finishAction>
    <wpml:exitOnRCLost>executeLostAction</wpml:exitOnRCLost>
    <wpml:executeRCLostAction>goBack</wpml:executeRCLostAction>
    <wpml:takeOffSecurityHeight>{_num(MIN_ALT)}</wpml:takeOffSecurityHeight>
    <wpml:globalTransitionalSpeed>{_num(speed)}</wpml:globalTransitionalSpeed>
    <wpml:globalRTHHeight>{_num(rth)}</wpml:globalRTHHeight>
    <wpml:droneInfo><wpml:droneEnumValue>{int(drone_enum[0])}</wpml:droneEnumValue><wpml:droneSubEnumValue>{int(drone_enum[1])}</wpml:droneSubEnumValue></wpml:droneInfo>
    <wpml:payloadInfo><wpml:payloadEnumValue>{int(payload_enum)}</wpml:payloadEnumValue><wpml:payloadPositionIndex>0</wpml:payloadPositionIndex></wpml:payloadInfo>
  </wpml:missionConfig>"""
    template = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:wpml="{WPML_NS}">
<Document>
  <wpml:author>AI Security Command Center</wpml:author>
  <wpml:createTime>{ms}</wpml:createTime>
  <wpml:updateTime>{ms}</wpml:updateTime>
{mission}
  <Folder>
    <wpml:templateType>waypoint</wpml:templateType>
    <wpml:templateId>0</wpml:templateId>
    <wpml:autoFlightSpeed>{_num(speed)}</wpml:autoFlightSpeed>
    <wpml:waylineCoordinateSysParam><wpml:coordinateMode>WGS84</wpml:coordinateMode><wpml:heightMode>relativeToStartPoint</wpml:heightMode></wpml:waylineCoordinateSysParam>
    <wpml:globalHeight>{_num(alt)}</wpml:globalHeight>
    <wpml:caliFlightEnable>0</wpml:caliFlightEnable>
    <wpml:gimbalPitchMode>usePointSetting</wpml:gimbalPitchMode>
  </Folder>
</Document>
</kml>
"""
    marks = []
    for i, p in enumerate(points):
        actions = ""
        if i == 0:
            actions += _action_group(i, 0, [("gimbalRotate", f"<wpml:gimbalPitchRotateEnable>1</wpml:gimbalPitchRotateEnable>"
                                             f"<wpml:gimbalPitchRotateAngle>{_num(GIMBAL_PITCH)}</wpml:gimbalPitchRotateAngle>"
                                             "<wpml:gimbalRotateMode>absoluteAngle</wpml:gimbalRotateMode>"
                                             "<wpml:payloadPositionIndex>0</wpml:payloadPositionIndex>")])
        if p["stop"] and pause_s > 0:
            actions += _action_group(i, 1, [("hover", f"<wpml:hoverTime>{_num(pause_s)}</wpml:hoverTime>")])
        marks.append(f"""      <Placemark>
        <Point><coordinates>{_num(p['lon'])},{_num(p['lat'])}</coordinates></Point>
        <wpml:index>{i}</wpml:index>
        <wpml:executeHeight>{_num(alt)}</wpml:executeHeight>
        <wpml:waypointSpeed>{_num(speed)}</wpml:waypointSpeed>
        <wpml:waypointHeadingParam><wpml:waypointHeadingMode>followWayline</wpml:waypointHeadingMode></wpml:waypointHeadingParam>
        <wpml:waypointTurnParam><wpml:waypointTurnMode>toPointAndStopWithDiscontinuityCurvature</wpml:waypointTurnMode><wpml:waypointTurnDampingDist>0</wpml:waypointTurnDampingDist></wpml:waypointTurnParam>
        <wpml:useStraightLine>1</wpml:useStraightLine>
{actions}      </Placemark>""")
    waylines = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:wpml="{WPML_NS}">
<Document>
{mission}
  <Folder>
    <wpml:templateId>0</wpml:templateId>
    <wpml:executeHeightMode>relativeToStartPoint</wpml:executeHeightMode>
    <wpml:waylineId>0</wpml:waylineId>
    <wpml:distance>{_num(round(total, 1))}</wpml:distance>
    <wpml:duration>{_num(round(duration, 1))}</wpml:duration>
    <wpml:autoFlightSpeed>{_num(speed)}</wpml:autoFlightSpeed>
{chr(10).join(marks)}
  </Folder>
</Document>
</kml>
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("wpmz/template.kml", template)
        z.writestr("wpmz/waylines.wpml", waylines)
    return buf.getvalue()


def _action_group(point_index, group_id, actions):
    body = "".join(f"""
          <wpml:action><wpml:actionId>{k}</wpml:actionId><wpml:actionActuatorFunc>{func}</wpml:actionActuatorFunc>
            <wpml:actionActuatorFuncParam>{param}</wpml:actionActuatorFuncParam></wpml:action>""" for k, (func, param) in enumerate(actions))
    return f"""        <wpml:actionGroup>
          <wpml:actionGroupId>{group_id}</wpml:actionGroupId><wpml:actionGroupStartIndex>{point_index}</wpml:actionGroupStartIndex>
          <wpml:actionGroupEndIndex>{point_index}</wpml:actionGroupEndIndex><wpml:actionGroupMode>sequence</wpml:actionGroupMode>
          <wpml:actionTrigger><wpml:actionTriggerType>reachPoint</wpml:actionTriggerType></wpml:actionTrigger>{body}
        </wpml:actionGroup>
"""


def read_kmz(data):
    """The waypoints of a KMZ made here: [{"lat", "lon", "alt", "speed", "hover"}] (the simulator and tests use it)."""
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("wpmz/waylines.wpml"))
    ns = {"k": "http://www.opengis.net/kml/2.2", "w": WPML_NS}
    out = []
    for pm in root.iter("{http://www.opengis.net/kml/2.2}Placemark"):
        lon, lat = (float(x) for x in pm.find("k:Point/k:coordinates", ns).text.split(","))
        hover = pm.find(".//w:hoverTime", ns)
        out.append({"lat": lat, "lon": lon, "alt": float(pm.find("w:executeHeight", ns).text),
                    "speed": float(pm.find("w:waypointSpeed", ns).text), "hover": float(hover.text) if hover is not None else 0.0})
    return out


def fingerprint(data):
    return hashlib.md5(data).hexdigest()

