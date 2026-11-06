"""The main dashboard page (Jinja template): live feeds, events, people, vehicles."""
PAGE = r"""
<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>
AI Security Command Center
</title>


<style>

* {
    box-sizing: border-box;
}

.event .event-drone {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 6px 0;
}

.event .event-drone img {
    width: 96px !important;
    height: auto !important;
    border: 1px solid #155879;
    border-radius: 3px;
}

.event .event-clip {
    color: #5bd9ff;
    font-size: 10px;
    letter-spacing: 1px;
    text-decoration: none;
    border: 1px solid #155879;
    border-radius: 3px;
    padding: 3px 7px;
}

.confirm-armed {
    background: #7a1020 !important;
    border-color: #ff4d6a !important;
    color: #fff !important;
}

html,
body {
    margin: 0;
    min-height: 100%;
}

body {
    background: #02070c;
    color: #d9efff;

    font-family:
        Arial,
        Helvetica,
        sans-serif;

    overflow-x: hidden;
}


body::before {
    content: "";

    position: fixed;
    inset: 0;

    pointer-events: none;

    background-image:
        linear-gradient(
            rgba(20,135,180,.025) 1px,
            transparent 1px
        ),
        linear-gradient(
            90deg,
            rgba(20,135,180,.025) 1px,
            transparent 1px
        );

    background-size:
        40px 40px;
}


/* ==========================================================
   TOP BAR
   ========================================================== */

.topbar {
    height: 74px;

    position: relative;
    z-index: 20;

    display: grid;

    grid-template-columns:
        270px
        1fr
        200px;

    background: #03101a;

    border-bottom:
        1px solid #0876ad;

    box-shadow:
        0 0 26px
        rgba(0,153,255,.10);
}


.brand {
    display: flex;
    align-items: center;

    gap: 11px;

    padding:
        0 18px;

    border-right:
        1px solid #12405a;
}


.brand-shield {
    width: 43px;
    height: 48px;

    display: flex;

    align-items: center;
    justify-content: center;

    clip-path:
        polygon(
            50% 0,
            92% 15%,
            84% 74%,
            50% 100%,
            16% 74%,
            8% 15%
        );

    background:
        rgba(18,151,215,.20);

    color: #45d0ff;

    font-size: 19px;

    border:
        1px solid #31c6ff;
}


.brand-name {
    color: #5bd9ff;

    font-size: 18px;

    font-weight: bold;

    letter-spacing: 2px;
}


.brand-sub {
    margin-top: 2px;

    color: #4a91b2;

    font-size: 8px;

    letter-spacing: 2px;
}


.status-strip {
    display: grid;

    grid-template-columns:
        repeat(
            5,
            minmax(95px,1fr)
        )
        minmax(
            160px,
            1.6fr
        );
}


.status-box {
    position: relative;

    display: flex;

    flex-direction: column;

    justify-content: center;

    padding:
        8px 12px;

    border-right:
        1px solid #123447;

    overflow: hidden;
}


.status-box::after {
    content: "";

    position: absolute;

    bottom: 0;
    left: -100%;

    width: 100%;
    height: 1px;

    background:
        linear-gradient(
            90deg,
            transparent,
            #36cfff,
            transparent
        );

    animation:
        topSweep
        4s linear infinite;
}


@keyframes topSweep {
    to {
        left: 100%;
    }
}


.status-label {
    color: #6d8b9d;

    font-size: 8px;

    letter-spacing: 1px;
}


.status-value {
    margin-top: 5px;

    display: flex;

    align-items: center;

    gap: 6px;

    color: #24ed87;

    font-size: 9px;

    font-weight: bold;
}


.dot {
    width: 7px;
    height: 7px;

    border-radius: 50%;

    background: #26ee89;

    box-shadow:
        0 0 10px #26ee89;

    animation:
        pulseDot
        1.4s infinite;
}


.dot.blue {
    background: #25c7ff;

    box-shadow:
        0 0 10px #25c7ff;
}


@keyframes pulseDot {
    50% {
        opacity: .35;

        transform:
            scale(.7);
    }
}


/* ==========================================================
   TOP WAVE
   ========================================================== */

.wave-title {
    color: #6c8c9e;

    font-size: 8px;

    letter-spacing: 1px;
}


.wave {
    height: 34px;

    margin-top: 3px;

    display: flex;

    align-items: center;

    gap: 3px;
}


.wave span {
    width: 3px;

    border-radius: 4px;

    background:
        linear-gradient(
            #2eef88,
            #24bfff
        );

    animation:
        waveform
        1.05s
        ease-in-out
        infinite;
}


.wave span:nth-child(1){height:8px}
.wave span:nth-child(2){height:22px}
.wave span:nth-child(3){height:13px}
.wave span:nth-child(4){height:29px}
.wave span:nth-child(5){height:16px}
.wave span:nth-child(6){height:25px}
.wave span:nth-child(7){height:10px}
.wave span:nth-child(8){height:31px}
.wave span:nth-child(9){height:14px}
.wave span:nth-child(10){height:25px}
.wave span:nth-child(11){height:11px}
.wave span:nth-child(12){height:29px}
.wave span:nth-child(13){height:17px}
.wave span:nth-child(14){height:23px}
.wave span:nth-child(15){height:9px}


@keyframes waveform {
    50% {
        transform:
            scaleY(.30);

        opacity: .45;
    }
}


.clock-area {
    display: flex;

    flex-direction: column;

    justify-content: center;

    align-items: flex-end;

    padding-right: 19px;
}


.clock {
    font-size: 19px;

    color: #edf8ff;
}


.date {
    margin-top: 3px;

    color: #5d8398;

    font-size: 8px;
}


/* ==========================================================
   MAIN GRID
   ========================================================== */

.app-grid {
    position: relative;
    z-index: 5;

    display: grid;

    grid-template-columns:
        205px
        minmax(0,1fr)
        400px;

    gap: 10px;

    max-width: 1740px;

    margin: auto;

    padding: 10px;
}


/* ==========================================================
   MATRIX LEFT SIDE
   ========================================================== */

.left-column {
    position: relative;

    min-height: 900px;

    overflow: hidden;

    border-right:
        1px solid
        rgba(0,165,91,.14);
}


#matrixCanvas {
    position: absolute;

    inset: 0;

    width: 100%;
    height: 100%;

    opacity: .55;

    z-index: 0;
}


.left-content {
    position: relative;

    z-index: 2;

    padding:
        355px 8px 8px;
}


.left-card {
    margin-bottom: 10px;

    padding: 10px;

    background:
        rgba(2,13,18,.84);

    border:
        1px solid #095070;

    border-radius: 5px;

    backdrop-filter:
        blur(4px);
}


.left-title {
    color: #8eb4c6;

    font-size: 8px;

    letter-spacing: 1px;

    margin-bottom: 11px;
}


.metric {
    margin-bottom: 13px;
}


.metric-head {
    display: flex;

    justify-content:
        space-between;

    font-size: 8px;

    color: #7392a2;
}


.metric-value {
    color: #23cfff;
}


.bar {
    height: 3px;

    margin-top: 6px;

    background: #10232d;
}


.bar-fill {
    height: 100%;

    background:
        linear-gradient(
            90deg,
            #17df78,
            #23cfff
        );

    animation:
        glowBar
        2s alternate infinite;
}


@keyframes glowBar {
    to {
        filter:
            brightness(1.55);
    }
}


.network-line {
    height: 25px;

    display: flex;

    align-items: flex-end;

    gap: 2px;

    margin-top: 5px;
}


.network-line span {
    width: 3px;

    background: #21de79;

    animation:
        networkPulse
        1.2s
        ease-in-out infinite;
}


.network-line span:nth-child(1){height:5px}
.network-line span:nth-child(2){height:12px}
.network-line span:nth-child(3){height:8px}
.network-line span:nth-child(4){height:18px}
.network-line span:nth-child(5){height:10px}
.network-line span:nth-child(6){height:20px}
.network-line span:nth-child(7){height:7px}
.network-line span:nth-child(8){height:15px}
.network-line span:nth-child(9){height:11px}
.network-line span:nth-child(10){height:22px}


@keyframes networkPulse {
    50% {
        transform:
            scaleY(.4);
    }
}


/* ==========================================================
   PANELS
   ========================================================== */

.panel {
    position: relative;

    overflow: hidden;

    background: #04111b;

    border:
        1px solid #0a5480;

    border-radius: 6px;

    box-shadow:
        0 0 20px
        rgba(0,126,188,.08);
}


.panel::before {
    content: "";

    position: absolute;

    top: 0;
    left: 0;

    width: 130px;
    height: 1px;

    background:
        linear-gradient(
            90deg,
            #36cfff,
            transparent
        );
}


.panel-head {
    height: 43px;

    display: flex;

    align-items: center;

    justify-content:
        space-between;

    padding:
        0 12px;

    border-bottom:
        1px solid #123447;
}


.panel-title {
    color: #a8c7d7;

    font-size: 9px;

    letter-spacing: 1px;
}


.live {
    color: #2aea88;

    font-size: 8px;
}


/* ==========================================================
   CAMERA
   ========================================================== */

.camera-box {
    position: relative;

    background: #000;
}


.camera {
    width: 100%;

    display: block;

    min-height: 470px;

    object-fit: contain;
}


.corner {
    position: absolute;

    width: 34px;
    height: 34px;
}


.tl {
    top: 14px;
    left: 14px;

    border-top:
        2px solid #3dd8ff;

    border-left:
        2px solid #3dd8ff;
}


.tr {
    top: 14px;
    right: 14px;

    border-top:
        2px solid #3dd8ff;

    border-right:
        2px solid #3dd8ff;
}


.bl {
    bottom: 14px;
    left: 14px;

    border-bottom:
        2px solid #3dd8ff;

    border-left:
        2px solid #3dd8ff;
}


.br {
    bottom: 14px;
    right: 14px;

    border-bottom:
        2px solid #3dd8ff;

    border-right:
        2px solid #3dd8ff;
}


.camera-footer {
    height: 28px;

    display: flex;

    align-items: center;

    justify-content:
        space-between;

    padding:
        0 10px;

    color: #5d8499;

    font-size: 8px;
}


.cam-name {
    color: #35caff;
}


/* ==========================================================
   STATS
   ========================================================== */

.stats {
    display: grid;

    grid-template-columns:
        repeat(4,1fr);

    gap: 8px;

    margin-top: 9px;
}


.stat-card {
    min-height: 95px;

    position: relative;

    padding: 13px;

    overflow: hidden;

    background: #05131d;

    border:
        1px solid #10496a;

    border-radius: 5px;
}


.stat-title {
    color: #42c6f5;

    font-size: 8px;

    letter-spacing: 1px;
}


.stat-number {
    margin-top: 11px;

    font-size: 24px;

    color: #effaff;
}


.stat-sub {
    color: #607f90;

    font-size: 8px;

    margin-top: 2px;
}


.stat-line {
    position: absolute;

    left: 10px;
    right: 10px;
    bottom: 9px;

    height: 14px;

    background:
        repeating-linear-gradient(
            90deg,
            transparent 0 7px,
            #20bfff 8px 9px,
            transparent 10px 15px
        );

    opacity: .35;

    animation:
        slideLine
        4s linear infinite;
}


@keyframes slideLine {
    from {
        transform:
            translateX(-20px);
    }

    to {
        transform:
            translateX(20px);
    }
}


/* ==========================================================
   RIGHT AI SCANNERS
   ========================================================== */

.ai-body {
    padding: 9px;
}


.scanner-row {
    display: grid;

    grid-template-columns:
        175px 1fr;

    gap: 8px;

    margin-bottom: 9px;
}


.scanner {
    height: 164px;

    position: relative;

    overflow: hidden;

    background:
        radial-gradient(
            circle,
            rgba(0,143,255,.17),
            rgba(0,27,50,.3) 47%,
            rgba(0,4,9,.65) 74%
        );

    border:
        1px solid #07537d;

    border-radius: 5px;
}


.scanner-label {
    position: absolute;

    top: 8px;
    left: 9px;

    color: #6bd8ff;

    font-size: 8px;

    letter-spacing: 1px;
}


.ring {
    position: absolute;

    border-radius: 50%;

    border:
        1px solid
        rgba(50,196,255,.38);

    animation:
        rotate
        7s linear infinite;
}


.ring1 {
    inset: 25px;
}


.ring2 {
    inset: 38px;

    border-style: dashed;

    animation-direction:
        reverse;

    animation-duration: 5s;
}


.ring3 {
    inset: 53px;

    animation-duration:
        3.5s;
}


@keyframes rotate {
    to {
        transform:
            rotate(360deg);
    }
}


.scanline {
    position: absolute;

    left: 14px;
    right: 14px;

    height: 1px;

    background: #42d9ff;

    box-shadow:
        0 0 10px #42d9ff;

    animation:
        scanLine
        2.3s
        ease-in-out infinite;
}


@keyframes scanLine {
    0% {
        top: 31px;
    }

    50% {
        top: 135px;
    }

    100% {
        top: 31px;
    }
}


.face {
    position: absolute;

    left: 50%;
    top: 53%;

    transform:
        translate(-50%,-50%);

    width: 65px;
    height: 82px;

    border:
        1px solid #2acbff;

    border-radius:
        44% 44% 48% 48%;

    box-shadow:
        0 0 22px
        rgba(42,203,255,.22);
}


.face::before {
    content: "";

    position: absolute;

    left: 12px;
    right: 12px;

    top: 28px;

    height: 1px;

    background: #31cfff;

    box-shadow:
        0 15px 0
        rgba(49,207,255,.7),
        0 30px 0
        rgba(49,207,255,.4);
}


.car {
    position: absolute;

    left: 50%;
    top: 56%;

    transform:
        translate(-50%,-50%);

    width: 105px;
    height: 44px;

    border:
        2px solid #2acbff;

    border-radius:
        23px 23px 10px 10px;

    box-shadow:
        0 0 23px
        rgba(42,203,255,.20);
}


.car::before {
    content: "";

    position: absolute;

    left: 20px;
    right: 20px;

    top: -31px;

    height: 31px;

    border:
        2px solid #2acbff;

    border-bottom: 0;

    border-radius:
        25px 25px 0 0;
}


.light {
    position: absolute;

    top: 19px;

    width: 12px;
    height: 5px;

    background: #4fe0ff;

    box-shadow:
        0 0 10px #4fe0ff;
}


.left-light {
    left: 9px;
}


.right-light {
    right: 9px;
}


.scan-info {
    padding: 11px;

    background: #05131d;

    border:
        1px solid #12394f;

    border-radius: 5px;
}


.scan-title {
    color: #688a9c;

    font-size: 8px;
}


.scan-status {
    margin-top: 12px;

    display: flex;

    align-items: center;

    gap: 9px;

    color: #27ef88;

    font-size: 16px;

    font-weight: bold;
}


.shield {
    width: 31px;
    height: 36px;

    display: flex;

    align-items: center;
    justify-content: center;

    clip-path:
        polygon(
            50% 0,
            92% 16%,
            83% 74%,
            50% 100%,
            17% 74%,
            8% 16%
        );

    background:
        rgba(44,238,140,.16);

    color: #34ef92;
}


.scan-detail {
    margin-top: 13px;

    padding-top: 9px;

    border-top:
        1px solid #163345;

    color: #6b8998;

    font-size: 8px;

    line-height: 1.8;
}


.scan-plate {
    margin-top: 8px;

    display: inline-block;

    padding:
        4px 8px;

    border:
        1px solid #168bc7;

    color: #4cd4ff;

    font-size: 17px;

    letter-spacing: 2px;
}


/* ==========================================================
   CONTROL BUTTONS
   ========================================================== */

.security-controls {
    display: grid;

    grid-template-columns:
        1fr 1fr;

    gap: 7px;

    margin:
        12px 0;
}


.security-button {
    min-height: 41px;

    cursor: pointer;

    color: #75bcd9;

    background: #061722;

    border:
        1px solid #155276;

    border-radius: 5px;

    font-size: 8px;

    letter-spacing: .8px;

    transition: .18s ease;
}


.security-button:hover {
    color: #e7faff;

    border-color: #32cfff;

    background: #082131;
}


.face-button {
    color: #45d4ff;

    border-color: #1189be;
}


.vehicle-button {
    color: #49e7a0;

    border-color: #16845b;
}



/* ==========================================================
   VOICE CONTROL
   ========================================================== */

.voice-button {
    grid-column: 1 / -1;
    min-height: 48px;
    position: relative;
    overflow: hidden;
    color: #70e8ff;
    border-color: #157da7;
    background: linear-gradient(90deg, rgba(0,112,160,.16), rgba(0,204,160,.08));
}

.voice-button.listening {
    color: #eaffff;
    border-color: #31e7ff;
    box-shadow: 0 0 18px rgba(49,231,255,.24), inset 0 0 22px rgba(49,231,255,.08);
}

.voice-button.listening::after {
    content: "";
    position: absolute;
    left: -45%;
    top: 0;
    width: 45%;
    height: 100%;
    background: linear-gradient(90deg, transparent, rgba(80,239,255,.18), transparent);
    animation: voiceSweep 1.1s linear infinite;
}

@keyframes voiceSweep { to { left: 110%; } }

.voice-console {
    grid-column: 1 / -1;
    min-height: 58px;
    padding: 9px 10px;
    background: rgba(2,15,24,.78);
    border: 1px solid #123f58;
    border-radius: 5px;
}

.voice-console-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    color: #5f91a8;
    font-size: 7px;
    letter-spacing: 1px;
}

.voice-state { color: #32d8ff; }
.voice-state.active {
    color: #2fee91;
    text-shadow: 0 0 8px rgba(47,238,145,.45);
}

.voice-transcript {
    margin-top: 7px;
    min-height: 15px;
    color: #a9d6e8;
    font-size: 9px;
    line-height: 1.45;
}

.voice-hint {
    margin-top: 6px;
    color: #4f7283;
    font-size: 7px;
    line-height: 1.5;
}

.voice-bars {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    height: 12px;
    vertical-align: middle;
    margin-right: 5px;
}

.voice-bars span {
    width: 2px;
    height: 4px;
    background: #37dbff;
    opacity: .45;
}

.voice-button.listening .voice-bars span {
    opacity: 1;
    animation: voiceBar .65s ease-in-out infinite alternate;
}
.voice-button.listening .voice-bars span:nth-child(2) { animation-delay: .1s; }
.voice-button.listening .voice-bars span:nth-child(3) { animation-delay: .2s; }
.voice-button.listening .voice-bars span:nth-child(4) { animation-delay: .3s; }
.voice-button.listening .voice-bars span:nth-child(5) { animation-delay: .4s; }
@keyframes voiceBar { to { height: 16px; } }

/* ==========================================================
   RECOGNITION CARDS
   ========================================================== */

.rec-title {
    margin:
        12px 0 8px;

    color: #9ab6c5;

    font-size: 9px;

    letter-spacing: 1px;
}


.rec-card {
    margin-bottom: 7px;

    padding: 10px;

    border-radius: 5px;
}


.person-card {
    border:
        1px solid #0aaa61;

    background:
        linear-gradient(
            90deg,
            rgba(0,156,79,.15),
            rgba(0,45,25,.04)
        );
}


.vehicle-card {
    border:
        1px solid #0b76ae;

    background:
        linear-gradient(
            90deg,
            rgba(0,112,176,.16),
            rgba(0,37,69,.04)
        );
}


.unknown-person {
    border:
        1px solid #bf2a39;

    background:
        rgba(178,19,37,.16);
}


.unknown-vehicle {
    border:
        1px solid #a96c05;

    background:
        rgba(183,109,0,.16);
}


.rec-row {
    display: flex;

    align-items: center;

    gap: 10px;
}


.rec-icon {
    width: 43px;
    height: 43px;

    display: flex;

    align-items: center;
    justify-content: center;

    border-radius: 4px;

    font-size: 21px;
}


.person-card .rec-icon {
    border:
        1px solid #0aa862;

    color: #24ed88;
}


.vehicle-card .rec-icon {
    border:
        1px solid #0d79b0;

    color: #31caff;
}


.rec-info {
    flex: 1;
}


.rec-label {
    font-size: 8px;
}


.person-card .rec-label {
    color: #49e6a1;
}


.vehicle-card .rec-label {
    color: #3cc7ff;
}


.unknown-person .rec-label {
    color: #ff5665;
}


.unknown-vehicle .rec-label {
    color: #ffb62b;
}


.rec-name {
    margin-top: 3px;

    color: #eff9ff;

    font-size: 16px;
}


.rec-sub {
    margin-top: 2px;

    color: #708c9b;

    font-size: 8px;
}


.check {
    width: 20px;
    height: 20px;

    display: flex;

    align-items: center;
    justify-content: center;

    border-radius: 50%;

    color: #002511;

    background: #2fed91;

    font-weight: bold;
}


.plate-box {
    padding:
        4px 8px;

    border:
        1px solid #278fca;

    background:
        rgba(18,101,151,.16);

    color: #daf5ff;

    border-radius: 3px;
}


.waiting {
    padding: 15px;

    color: #557788;

    text-align: center;

    border:
        1px solid #143447;

    border-radius: 5px;
}


/* ==========================================================
   EVENT HISTORY
   ========================================================== */

.history {
    margin-top: 9px;
}


.events {
    display: grid;

    grid-template-columns:
        repeat(
            auto-fill,
            minmax(170px,1fr)
        );

    gap: 7px;

    padding: 8px;
}


.event {
    overflow: hidden;

    background: #05131d;

    border:
        1px solid #153c56;

    border-radius: 5px;
}


.event img {
    width: 100%;
    height: 92px;

    object-fit: cover;

    display: block;
}


.event-body {
    padding: 7px;
}


.event-type {
    color: #36c8ff;

    font-size: 7px;
}


.event-name {
    margin-top: 3px;

    color: #e7f5fc;

    font-size: 10px;
}


.event-meta {
    margin-top: 3px;

    color: #557486;

    font-size: 7px;
}


.delete-event-button {
    width: 100%;
    min-height: 30px;
    margin-top: 8px;
    cursor: pointer;
    color: #ff6675;
    background: rgba(130,14,30,.10);
    border: 1px solid #702935;
    border-radius: 4px;
    font-size: 7px;
    letter-spacing: 1px;
    transition: .18s ease;
}

.delete-event-button:hover {
    color: #fff;
    background: rgba(198,21,43,.30);
    border-color: #ff4c61;
    box-shadow: 0 0 12px rgba(255,62,84,.18);
}

.event-head-actions {
    display: flex;
    align-items: center;
    gap: 7px;
}

.history-action-button {
    min-height: 25px;
    padding: 0 9px;
    cursor: pointer;
    color: #66dfff;
    background: rgba(14,88,128,.12);
    border: 1px solid #155879;
    border-radius: 4px;
    font-size: 7px;
    letter-spacing: 1px;
}

.history-action-button:hover {
    color: #fff;
    border-color: #35cbff;
    box-shadow: 0 0 12px rgba(53,203,255,.16);
}

.history-action-button.danger {
    color: #ff7b86;
    border-color: #7a2935;
    background: rgba(125,12,28,.12);
}

.history-action-button.danger:hover {
    color: #fff;
    border-color: #ff4c61;
    background: rgba(190,18,40,.28);
}

.history-overlay {
    position: fixed;
    inset: 0;
    z-index: 10050;
    display: none;
    padding: 18px;
    background: rgba(0,5,10,.96);
    backdrop-filter: blur(8px);
    overflow-y: auto;
}

.history-overlay.open {
    display: block;
}

.history-window {
    width: min(1500px, 96vw);
    min-height: 78vh;
    margin: 15px auto;
    background: #04111b;
    border: 1px solid #0a6390;
    border-radius: 7px;
    box-shadow: 0 0 32px rgba(0,170,255,.12);
}

.history-window-head {
    position: sticky;
    top: 0;
    z-index: 3;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    min-height: 54px;
    padding: 10px 14px;
    background: rgba(3,16,26,.97);
    border-bottom: 1px solid #123f58;
}

.history-window-title {
    color: #62d8ff;
    font-size: 11px;
    letter-spacing: 2px;
}

.history-window-sub {
    margin-top: 3px;
    color: #66899a;
    font-size: 7px;
}

.full-history-events {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
    gap: 10px;
    padding: 12px;
}

.full-history-events .event img {
    height: 120px;
}

.unknown-event-badge {
    display: inline-block;
    margin-top: 5px;
    padding: 3px 6px;
    color: #ffb34d;
    border: 1px solid rgba(255,161,48,.55);
    background: rgba(160,83,0,.12);
    border-radius: 3px;
    font-size: 7px;
    letter-spacing: 1px;
}


/* ==========================================================
   MODALS
   ========================================================== */

.enroll-overlay {
    position: fixed;

    inset: 0;

    z-index: 9999;

    display: none;

    align-items: center;
    justify-content: center;

    padding: 20px;

    background:
        rgba(0,5,10,.92);

    backdrop-filter:
        blur(8px);
}


.enroll-overlay.open {
    display: flex;
}


.enroll-window {
    width:
        min(900px,96vw);

    overflow: hidden;

    border-radius: 8px;

    border:
        1px solid #118bc2;

    background:
        linear-gradient(
            145deg,
            #061923,
            #020a10
        );

    box-shadow:
        0 0 55px
        rgba(0,167,255,.18);
}


.enroll-header {
    height: 53px;

    display: flex;

    align-items: center;

    justify-content:
        space-between;

    padding:
        0 17px;

    color: #5cdaff;

    font-size: 10px;

    letter-spacing: 1.7px;

    border-bottom:
        1px solid #16445c;
}


.close-enroll {
    width: 35px;
    height: 35px;

    cursor: pointer;

    border: 0;

    background:
        transparent;

    color: #79aaba;

    font-size: 23px;
}


/* ==========================================================
   FACE ENROLLMENT
   ========================================================== */

.enroll-content {
    display: grid;

    grid-template-columns:
        1.35fr 1fr;

    gap: 16px;

    padding: 17px;
}


.enroll-scanner {
    min-height: 450px;

    position: relative;

    overflow: hidden;

    border:
        1px solid #087fb5;

    border-radius: 7px;

    background: #000;
}


.enroll-live-camera {
    position: absolute;

    inset: 0;

    width: 100%;
    height: 100%;

    object-fit: cover;

    opacity: .48;

    filter:
        saturate(.55)
        contrast(1.15)
        brightness(.72);
}


.enroll-blue-filter {
    position: absolute;

    inset: 0;

    background:
        radial-gradient(
            circle at center,
            rgba(0,182,255,.06),
            rgba(0,28,47,.20) 55%,
            rgba(0,5,10,.48)
        );

    pointer-events: none;
}


.enroll-grid {
    position: absolute;

    inset: 0;

    background-image:
        linear-gradient(
            rgba(37,193,255,.06) 1px,
            transparent 1px
        ),
        linear-gradient(
            90deg,
            rgba(37,193,255,.06) 1px,
            transparent 1px
        );

    background-size:
        28px 28px;
}


.enroll-ring {
    position: absolute;

    border-radius: 50%;

    border:
        1px solid
        rgba(39,200,255,.45);
}


.ring-a {
    inset:
        55px 65px;

    animation:
        enrollRotate
        8s linear infinite;
}


.ring-b {
    inset:
        85px 95px;

    border-style: dashed;

    animation:
        enrollRotateReverse
        5s linear infinite;
}


.ring-c {
    inset:
        115px 125px;

    animation:
        enrollRotate
        3s linear infinite;
}


@keyframes enrollRotate {
    to {
        transform:
            rotate(360deg);
    }
}


@keyframes enrollRotateReverse {
    to {
        transform:
            rotate(-360deg);
    }
}


.face-target {
    position: absolute;

    width: 150px;
    height: 200px;

    left: 50%;
    top: 47%;

    transform:
        translate(-50%,-50%);

    border:
        2px solid #29d1ff;

    border-radius:
        44% 44% 48% 48%;

    box-shadow:
        0 0 32px
        rgba(35,207,255,.30),
        inset 0 0 30px
        rgba(35,207,255,.05);
}


.face-landmark {
    position: absolute;

    width: 5px;
    height: 5px;

    border-radius: 50%;

    background: #54e1ff;

    box-shadow:
        0 0 7px #54e1ff;
}


.lm1 {
    left: 33px;
    top: 64px;
}

.lm2 {
    right: 33px;
    top: 64px;
}

.lm3 {
    left: 72px;
    top: 100px;
}

.lm4 {
    left: 50px;
    bottom: 46px;
}

.lm5 {
    right: 50px;
    bottom: 46px;
}


.face-target::before {
    content: "";

    position: absolute;

    left: 23px;
    right: 23px;

    top: 66px;

    height: 1px;

    background:
        rgba(65,217,255,.7);

    box-shadow:
        0 37px 0
        rgba(65,217,255,.45),
        0 70px 0
        rgba(65,217,255,.25);
}


.enroll-scan-line {
    position: absolute;

    left: 8%;
    right: 8%;

    height: 2px;

    background:
        linear-gradient(
            90deg,
            transparent,
            #55e3ff,
            transparent
        );

    box-shadow:
        0 0 18px #31cfff;

    animation:
        biometricSweep
        1.7s ease-in-out infinite;
}


@keyframes biometricSweep {
    0% {
        top: 13%;
    }

    50% {
        top: 82%;
    }

    100% {
        top: 13%;
    }
}


.scanner-corner {
    position: absolute;

    width: 46px;
    height: 46px;
}


.ec1 {
    left: 16px;
    top: 16px;

    border-left:
        2px solid #42d8ff;

    border-top:
        2px solid #42d8ff;
}


.ec2 {
    right: 16px;
    top: 16px;

    border-right:
        2px solid #42d8ff;

    border-top:
        2px solid #42d8ff;
}


.ec3 {
    left: 16px;
    bottom: 16px;

    border-left:
        2px solid #42d8ff;

    border-bottom:
        2px solid #42d8ff;
}


.ec4 {
    right: 16px;
    bottom: 16px;

    border-right:
        2px solid #42d8ff;

    border-bottom:
        2px solid #42d8ff;
}


.scanner-message {
    position: absolute;

    left: 15px;
    right: 15px;
    bottom: 22px;

    padding: 9px;

    text-align: center;

    color: #63dbff;

    background:
        rgba(1,13,20,.72);

    border:
        1px solid
        rgba(37,191,244,.30);

    font-size: 9px;

    letter-spacing: 1.3px;
}


.enroll-panel {
    padding: 9px;
}


.enroll-label {
    margin-bottom: 7px;

    color: #6f93a5;

    font-size: 8px;

    letter-spacing: 1px;
}


.enroll-input {
    width: 100%;
    height: 44px;

    padding:
        0 12px;

    outline: none;

    color: #e7f8ff;

    background: #03111a;

    border:
        1px solid #145377;

    border-radius: 5px;

    font-size: 15px;
}


.enroll-input:focus {
    border-color: #30cfff;

    box-shadow:
        0 0 15px
        rgba(48,207,255,.12);
}


.security-note {
    margin-top: 14px;

    padding: 11px;

    color: #708d9c;

    background:
        rgba(0,116,169,.055);

    border:
        1px solid #153c51;

    font-size: 9px;

    line-height: 1.6;
}


.start-scan-button {
    width: 100%;

    min-height: 48px;

    margin-top: 15px;

    cursor: pointer;

    color: #001319;

    background:
        linear-gradient(
            90deg,
            #27cfff,
            #36e3b0
        );

    border: 0;

    border-radius: 5px;

    font-weight: bold;

    letter-spacing: 1px;
}


.start-scan-button:disabled {
    cursor: default;

    opacity: .45;
}


.cancel-scan-button {
    width: 100%;

    min-height: 40px;

    margin-top: 8px;

    cursor: pointer;

    color: #ff7481;

    background:
        rgba(117,18,29,.12);

    border:
        1px solid #7e2733;

    border-radius: 5px;
}


.progress-area {
    margin-top: 21px;
}


.progress-header {
    display: flex;

    justify-content:
        space-between;

    color: #68bad9;

    font-size: 8px;
}


.progress-track {
    height: 7px;

    margin-top: 8px;

    overflow: hidden;

    background: #0a202a;

    border-radius: 10px;
}


.progress-fill {
    width: 0%;

    height: 100%;

    background:
        linear-gradient(
            90deg,
            #18bfff,
            #26ed92
        );

    box-shadow:
        0 0 12px
        rgba(37,216,255,.50);

    transition:
        width .35s ease;
}


.enroll-message {
    min-height: 36px;

    margin-top: 10px;

    color: #81a3b3;

    font-size: 9px;

    line-height: 1.5;
}


.sample-dots {
    display: flex;

    gap: 8px;

    margin-top: 15px;
}


.sample-dot {
    width: 13px;
    height: 13px;

    border-radius: 50%;

    border:
        1px solid #1b6689;

    background: #071722;
}


.sample-dot.complete {
    border-color: #31eb93;

    background: #31eb93;

    box-shadow:
        0 0 8px
        rgba(49,235,147,.65);
}


/* ==========================================================
   VEHICLE / LIBRARY MODALS
   ========================================================== */

.small-window {
    width:
        min(680px,96vw);
}


.simple-body {
    padding: 18px;
}


.vehicle-enroll-body {
    display: grid;

    grid-template-columns:
        220px 1fr;

    gap: 18px;

    padding: 18px;
}


.mini-car-scanner {
    min-height: 260px;

    position: relative;

    overflow: hidden;

    border:
        1px solid #087eb5;

    background:
        radial-gradient(
            circle,
            rgba(0,151,255,.17),
            #020b11 70%
        );

    border-radius: 6px;
}


.mini-radar {
    position: absolute;

    inset: 30px;

    border-radius: 50%;

    border:
        1px dashed
        rgba(51,206,255,.45);

    animation:
        enrollRotate
        6s linear infinite;
}


.mini-car {
    position: absolute;

    left: 50%;
    top: 50%;

    transform:
        translate(-50%,-50%);

    font-size: 70px;

    filter:
        drop-shadow(
            0 0 13px
            rgba(44,201,255,.6)
        );
}


.vehicle-sweep {
    position: absolute;

    left: 15px;
    right: 15px;

    height: 1px;

    background: #3bd9ff;

    box-shadow:
        0 0 12px #3bd9ff;

    animation:
        biometricSweep
        2s infinite;
}


.vehicle-label-space {
    margin-top: 16px;
}


.plate-input {
    text-transform: uppercase;

    letter-spacing: 2px;
}


.library-grid {
    display: grid;

    grid-template-columns:
        repeat(
            auto-fill,
            minmax(180px,1fr)
        );

    gap: 9px;
}


.library-item {
    padding: 13px;

    border:
        1px solid #164766;

    border-radius: 5px;

    background: #05151f;
}


.library-type {
    color: #52d4ff;

    font-size: 8px;

    letter-spacing: 1px;
}


.library-name {
    margin-top: 7px;

    color: #eaf9ff;

    font-size: 15px;
}


.library-sub {
    margin-top: 4px;

    color: #6c8e9f;

    font-size: 9px;
}


/* ==========================================================
   RESPONSIVE
   ========================================================== */

@media(max-width:1250px) {
    .app-grid {
        grid-template-columns:
            160px 1fr;
    }

    .right-column {
        grid-column:
            1 / -1;
    }

    .topbar {
        grid-template-columns:
            230px 1fr;
    }

    .clock-area {
        display: none;
    }

    .status-box:nth-child(6) {
        display: none;
    }

    .status-strip {
        grid-template-columns:
            repeat(5,1fr);
    }
}


@media(max-width:850px) {
    .app-grid {
        grid-template-columns:
            1fr;
    }

    .left-column {
        display: none;
    }

    .stats {
        grid-template-columns:
            repeat(2,1fr);
    }

    .enroll-content,
    .vehicle-enroll-body {
        grid-template-columns:
            1fr;
    }

    .enroll-scanner {
        min-height: 380px;
    }
}

</style>

</head>


<body>


<!-- =======================================================
     TOP BAR
     ======================================================= -->

<div class="topbar">


<div class="brand">

<div class="brand-shield">
A
</div>

<div>

<div class="brand-name">
AI SECURITY
</div>

<div class="brand-sub">
COMMAND CENTER
</div>

</div>

</div>


<div class="status-strip">


<div class="status-box">

<div class="status-label">
SYSTEM
</div>

<div
    id="topSystem"
    class="status-value"
>

<span class="dot"></span>

PROTECTED

</div>

</div>


<div class="status-box">

<div class="status-label">
CAMERA
</div>

<div
    id="topCamera"
    class="status-value"
>

<span class="dot"></span>

ONLINE

</div>

</div>


<div class="status-box">

<div class="status-label">
FACE AI
</div>

<div class="status-value">

<span class="dot blue"></span>

ACTIVE

</div>

</div>


<div class="status-box">

<div class="status-label">
LPR AI
</div>

<div class="status-value">

<span class="dot blue"></span>

ACTIVE

</div>

</div>


<div class="status-box">

<div class="status-label">
MQTT
</div>

<div
    id="topMqtt"
    class="status-value"
>

<span class="dot"></span>

CONNECTED

</div>

</div>


<div class="status-box">

<div class="wave-title">
LIVE ACTIVITY
</div>

<div class="wave">

<span></span>
<span></span>
<span></span>
<span></span>
<span></span>

<span></span>
<span></span>
<span></span>
<span></span>
<span></span>

<span></span>
<span></span>
<span></span>
<span></span>
<span></span>

</div>

</div>


</div>


<div class="clock-area">

<div
    id="clock"
    class="clock"
>
--
</div>

<div
    id="date"
    class="date"
>
--
</div>

</div>


</div>

<!--HUD_SUBNAV-->

<!-- =======================================================
     MAIN APP
     ======================================================= -->

<div class="app-grid">


<!-- =======================================================
     MATRIX LEFT COLUMN
     ======================================================= -->

<div class="left-column">

<canvas id="matrixCanvas"></canvas>


<div class="left-content">


<div class="left-card">

<div class="left-title">
SYSTEM OVERVIEW
</div>


<div class="metric">

<div class="metric-head">

<span>
AI CORE
</span>

<span class="metric-value">
ACTIVE
</span>

</div>

<div class="bar">

<div
    class="bar-fill"
    style="width:87%"
></div>

</div>

</div>


<div class="metric">

<div class="metric-head">

<span>
CAMERA LINK
</span>

<span
    id="leftCamera"
    class="metric-value"
>
ONLINE
</span>

</div>

<div class="bar">

<div
    class="bar-fill"
    style="width:96%"
></div>

</div>

</div>


<div class="metric">

<div class="metric-head">

<span>
MQTT LINK
</span>

<span
    id="leftMqtt"
    class="metric-value"
>
CONNECTED
</span>

</div>

<div class="bar">

<div
    class="bar-fill"
    style="width:93%"
></div>

</div>

</div>


</div>


<div class="left-card">

<div class="left-title">
NETWORK ACTIVITY
</div>

<div class="metric-head">

<span>
DATA STREAM
</span>

<span class="metric-value">
LIVE
</span>

</div>


<div class="network-line">

<span></span>
<span></span>
<span></span>
<span></span>
<span></span>

<span></span>
<span></span>
<span></span>
<span></span>
<span></span>

</div>


<div
    style="
        color:#597a8c;
        font-size:8px;
        margin-top:10px;
        line-height:1.8;
    "
>

FRIGATE DATA LINK

<br>

FACE AI CHANNEL

<br>

LPR AI CHANNEL

<br>

MQTT EVENT BUS

</div>

</div>


</div>

</div>


<!-- =======================================================
     CENTER CAMERA
     ======================================================= -->

<div class="center-column">

<div id="cameraFeedPanel">
<div class="panel">

<div class="panel-head">

<div class="panel-title">
▣ LIVE CAMERA FEED
</div>

<div style="display:flex;align-items:center;gap:10px">
<div class="live">
● LIVE
</div>
<button type="button" class="feed-switch" data-feed-switch="main" aria-pressed="true" title="Show or hide this live feed">LIVE FEED <span class="knob"></span></button>
</div>

</div>


<div class="camera-box">

<div class="camera live-slot" data-live-camera data-live-deferred style="aspect-ratio:16/9;min-height:0"></div>

<div class="corner tl"></div>
<div class="corner tr"></div>
<div class="corner bl"></div>
<div class="corner br"></div>

</div>


<div class="camera-footer">

<div class="cam-name">
CAM 01
</div>

<div>
FRONT CAMERA • FACE AI • LPR AI
</div>

</div>

</div>
</div><!-- cameraFeedPanel -->


<div class="panel" style="margin-top:9px;">
<div class="panel-head">
<div class="panel-title">✈ DRONE LIVE FEED</div>
<div style="display:flex;align-items:center;gap:10px">
<div class="live" id="droneFeedState">DRONE</div>
<button type="button" class="feed-switch" data-feed-switch="drone" aria-pressed="true" title="Show or hide this live feed">LIVE FEED <span class="knob"></span></button>
</div>
</div>
<div class="camera-box" style="min-height:280px;">
<!-- Every drone shares this one feed: the tiles split the space and follow drones being added or removed. -->
<div class="dfg" id="droneFeedGrid">
<div class="dfg-tile" data-drone="drone">
<div id="droneCameraFeed" class="camera live-slot" data-live-camera="drone" data-live-deferred></div>
</div>
</div>
<div class="corner tl"></div><div class="corner tr"></div>
<div class="corner bl"></div><div class="corner br"></div>
</div>
<div class="camera-footer">
<div class="cam-name" id="droneFeedCount">DRONE 01</div>
<div id="droneTrackingReadout">TRACKING ASSIST • WAITING</div>
</div>
<style>
.dfg{display:grid;gap:4px;height:420px;grid-template-columns:repeat(var(--c,1),minmax(0,1fr));grid-template-rows:repeat(var(--r,1),minmax(0,1fr))}
.dfg-tile{position:relative;background:#000;overflow:hidden;min-height:0;border:1px solid #0f2f42}
.dfg-tile.gone{display:none}
.dfg-tile .live-slot,.dfg-tile .dfg-vcam{position:absolute;inset:0;width:100%;height:100%;min-height:0}
.dfg-tile .live-slot video{width:100%;height:100%;object-fit:contain}
.dfg-tile:fullscreen{border:0}
.dfg-head{position:absolute;left:0;right:0;top:0;z-index:600;display:flex;justify-content:space-between;align-items:center;gap:6px;padding:5px 7px;background:linear-gradient(rgba(2,10,16,.85),rgba(2,10,16,0));font-size:10px}
.dfg-head b{color:#e9f8ff;letter-spacing:1px}
.dfg-head i{display:inline-block;width:7px;height:7px;border-radius:50%;background:#53636d;margin-right:5px}
.dfg-head i.ok{background:#26ee89}.dfg-head i.half{background:#ffb23c}
.dfg-tag{font-size:8px;color:#ffcf7a;border:1px solid #7a5a12;border-radius:3px;padding:0 3px;margin-left:5px}
.dfg-btns{display:flex;gap:4px}
.dfg-btns a,.dfg-btns button{background:rgba(3,16,26,.85);border:1px solid #155879;color:#9edfff;border-radius:3px;padding:2px 6px;font:bold 9px Arial;letter-spacing:.5px;text-decoration:none;cursor:pointer}
.dfg-btns button.confirm-armed{background:#7a1020;border-color:#ff4d6a;color:#fff}
.dfg-hud{position:absolute;left:6px;right:6px;bottom:6px;z-index:600;display:flex;gap:4px;flex-wrap:wrap;pointer-events:none}
.dfg-hud span{background:rgba(3,16,26,.85);border:1px solid #155879;color:#9edfff;padding:1px 5px;border-radius:3px;font:bold 9px Arial}
.dfg-off{position:absolute;inset:0;display:none;align-items:center;justify-content:center;color:#6d8b9d;font:bold 11px Arial;letter-spacing:1px;text-align:center;padding:12px;z-index:550;pointer-events:none}
.dfg-tile .live-mode{top:auto!important;bottom:28px!important}
</style>
<div style="padding:6px 9px 9px"><a href="/drone-grid" style="color:#5bd9ff;font-size:10px;letter-spacing:1px;text-decoration:none">▦ ALL DRONES GRID VIEW / FULL SCREEN →</a></div>
<script>
(function () {
    const grid = document.getElementById("droneFeedGrid");
    const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
    const fmt = (v, d) => v == null || isNaN(v) ? "–" : Number(v).toFixed(d);
    const whenPlayer = fn => window.attachLiveCamera ? fn() : window.addEventListener("live-player-ready", fn, {once: true});
    const primary = grid.querySelector('[data-drone="drone"]');
    const tiles = {drone: primary};
    let leaflet = null;

    // Virtual drones have no video: show the satellite view under them instead (Leaflet loads only when needed).
    function needLeaflet() {
        if (window.L) return Promise.resolve();
        if (!leaflet) leaflet = new Promise(ok => {
            const css = document.createElement("link"); css.rel = "stylesheet"; css.href = "/vendor/leaflet/leaflet.css";
            const js = document.createElement("script"); js.src = "/vendor/leaflet/leaflet.js"; js.onload = ok;
            document.head.append(css, js);
        });
        return leaflet;
    }
    function vcam(t, x) {
        if (!x.lat) return;
        needLeaflet().then(() => {
            if (!t.isConnected) return;
            const z = x.altitude > 90 ? 16 : x.altitude > 45 ? 17 : x.altitude > 15 ? 18 : 19;
            if (!t._map) {
                t._map = L.map(t.querySelector(".dfg-vcam"), {zoomControl: false, attributionControl: false, dragging: false, scrollWheelZoom: false,
                    doubleClickZoom: false, boxZoom: false, keyboard: false, touchZoom: false});
                L.tileLayer("/tiles/sat/{z}/{x}/{y}", {maxZoom: 19}).addTo(t._map);
                t._map.setView([x.lat, x.lon], z);
            } else t._map.setView([x.lat, x.lon], z, {animate: false});
        });
    }

    function addParts(t, x) {
        t.insertAdjacentHTML("beforeend", '<div class="dfg-off"></div><div class="dfg-head"><span><i></i><b></b></span><span class="dfg-btns">'
            + '<a href="/drone-control?drone=' + encodeURIComponent(x.drone) + '">CONTROLS</a>'
            + '<button type="button" data-act="full" title="Full screen this drone">⛶</button>'
            + (!x.virtual && x.drone !== "drone" ? '<button type="button" data-act="remove" title="Remove this drone">✕</button>' : '')
            + '</span></div><div class="dfg-hud"></div>');
        const full = () => document.fullscreenElement ? document.exitFullscreen() : t.requestFullscreen?.();
        t.querySelector('[data-act="full"]').addEventListener("click", full);
        t.addEventListener("dblclick", full);
        t.querySelector('[data-act="remove"]')?.addEventListener("click", async e => {
            const btn = e.currentTarget;
            const reset = () => { btn.dataset.armed = ""; btn.textContent = "✕"; btn.classList.remove("confirm-armed"); btn.disabled = false; };
            if (btn.dataset.armed !== "1") {  // click again within 4 s to confirm
                btn.dataset.armed = "1"; btn.textContent = "REMOVE?"; btn.classList.add("confirm-armed");
                clearTimeout(btn._t); btn._t = setTimeout(reset, 4000);
                return;
            }
            clearTimeout(btn._t); btn.disabled = true; btn.textContent = "REMOVING…";
            try {
                const r = await fetch("/api/sources/" + encodeURIComponent(x.drone), {method: "DELETE"});
                const d = await r.json();
                if (!r.ok || !d.ok) throw new Error(d.error || "Could not remove");
                drop(x.drone);
            } catch (err) { alert(err.message); reset(); }
        });
    }
    function tileFor(x) {
        const t = document.createElement("div");
        t.className = "dfg-tile"; t.dataset.drone = x.drone;
        t.innerHTML = x.virtual ? '<div class="dfg-vcam"></div>' : '<div class="live-slot" data-live-camera="' + esc(x.drone) + '"></div>';
        if (!x.virtual && window.droneFeedOn !== false) whenPlayer(() => window.attachLiveCamera(t.querySelector(".live-slot")));
        return t;
    }
    function drop(name) {
        const t = tiles[name];
        if (!t || name === "drone") return;
        const s = t.querySelector(".live-slot");
        if (s) window.detachLiveCamera?.(s);
        t._map?.remove();
        t.remove(); delete tiles[name];
        layout();
    }
    function paint(t, x) {
        if (!t._parts) { addParts(t, x); t._parts = true; }
        t.querySelector(".dfg-head i").className = x.drone_connected ? "ok" : x.phone_connected ? "half" : "";
        t.querySelector(".dfg-head b").innerHTML = esc(x.label).toUpperCase() + (x.virtual ? '<span class="dfg-tag">VIRTUAL</span>' : '');
        const down = !x.phone_connected || !x.drone_connected, off = t.querySelector(".dfg-off");
        // Real drones may still send video with the phone link down, so only virtual tiles are blanked.
        off.style.display = x.virtual && down ? "flex" : "none";
        off.textContent = x.over_limit ? "OVER LICENCE LIMIT" : !x.phone_connected ? "NOT CONNECTED" : "DRONE OFF";
        const state = x.mission ? (x.mission === "route" ? "ROUTE" : x.mission === "backup" ? "BACKUP" : "RESPONSE") : x.flying ? "FLYING" : "ON GROUND";
        t.querySelector(".dfg-hud").innerHTML = x.over_limit ? "<span>OVER LICENCE LIMIT</span>" : !x.drone_connected ? ""
            : "<span>" + state + "</span><span>BAT " + (x.battery ?? "–") + "%</span><span>ALT " + fmt(x.altitude, 1) + " m</span>";
        if (x.virtual) vcam(t, x);
    }
    // 1 drone fills the feed, 2 side by side, 3-4 in a 2×2, then 3 per row; the feed grows a little with many drones.
    function layout() {
        const n = Object.values(tiles).filter(t => !t.classList.contains("gone")).length || 1;
        const c = n <= 1 ? 1 : n <= 4 ? 2 : 3, r = Math.ceil(n / c);
        grid.style.setProperty("--c", c); grid.style.setProperty("--r", r);
        grid.style.height = (r <= 1 ? 420 : r === 2 ? 480 : 600) + "px";
        document.getElementById("droneFeedCount").textContent = n > 1 ? n + " DRONES" : "DRONE 01";
        Object.values(tiles).forEach(t => t._map?.invalidateSize());
    }
    async function refresh() {
        let d;
        try { d = await fetch("/api/drone/links", {cache: "no-store"}).then(r => r.json()); } catch (e) { return; }
        if (!d.ok) return;
        const seen = new Set(d.drones.map(x => x.drone));
        // The first drone keeps its fixed tile; it is only hidden when other drones exist without it.
        primary.classList.toggle("gone", !seen.has("drone") && d.drones.length > 0);
        for (const x of d.drones) {
            if (!tiles[x.drone]) { tiles[x.drone] = tileFor(x); grid.appendChild(tiles[x.drone]); }
            paint(tiles[x.drone], x);
        }
        Object.keys(tiles).filter(k => !seen.has(k)).forEach(drop);
        layout();
    }
    document.addEventListener("fullscreenchange", () => setTimeout(layout, 100));
    refresh();
    setInterval(refresh, 3000);
})();
</script>
</div>


<!-- =======================================================
     MULTI-CAMERA GRID: every extra camera and drone
     ======================================================= -->
<style>
.multi-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px;padding:10px}
.grid-tile{position:relative;background:#000;border:1px solid #123447;border-radius:5px;overflow:hidden}
.grid-tile .live-slot{aspect-ratio:16/9;height:auto;cursor:zoom-in}
.grid-tile.feed-off .live-slot{display:none}
.grid-tile .tile-foot{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:6px 9px;font-size:9px;letter-spacing:1px;color:#5d8499;background:#03101a;flex-wrap:wrap}
.grid-tile .tile-name{color:#35caff;text-transform:uppercase}
.grid-tile .tile-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#ff5d6c;margin-right:6px}
.grid-tile .tile-dot.on{background:#26ee89;box-shadow:0 0 8px #26ee89}
.grid-tile .tile-dot.paused{background:#ffb23c;box-shadow:none}
.grid-tile .tile-actions{display:flex;gap:6px;align-items:center}
.tile-btn{min-height:22px;padding:0 8px;cursor:pointer;color:#66dfff;background:rgba(14,88,128,.12);border:1px solid #155879;border-radius:3px;font-size:8px;letter-spacing:1px;font-family:inherit}
.tile-btn:hover{color:#fff;border-color:#35cbff}
.tile-btn.danger{color:#ff7b86;border-color:#7a2935;background:rgba(125,12,28,.12)}
.tile-btn:disabled{opacity:.5;cursor:default}
.feed-off-note{display:none;padding:18px 12px;color:#6d8b9d;font-size:10px;letter-spacing:1px;text-align:center}
.panel.feed-off .camera-box{display:none}
.panel.feed-off .feed-off-note{display:block}
.feed-switch{display:inline-flex;align-items:center;gap:7px;min-height:22px;padding:0 8px;cursor:pointer;color:#2aea88;background:rgba(18,120,70,.10);border:1px solid #1f7a50;border-radius:12px;font-size:8px;letter-spacing:1px;font-family:inherit}
.feed-switch .knob{position:relative;display:inline-block;width:26px;height:14px;border-radius:7px;background:rgba(37,199,255,.18);border:1px solid #36cfff}
.feed-switch .knob::after{content:"";position:absolute;top:2px;left:13px;width:8px;height:8px;border-radius:50%;background:#45d0ff;box-shadow:0 0 6px #45d0ff;transition:.2s}
.feed-switch[aria-pressed="false"]{color:#6d8b9d;background:rgba(14,88,128,.08);border-color:#155879}
.feed-switch[aria-pressed="false"] .knob{background:#0a1c28;border-color:#155879}
.feed-switch[aria-pressed="false"] .knob::after{left:2px;background:#4d6b7c;box-shadow:none}
.grid-empty{padding:22px 14px;color:#6d8b9d;font-size:11px;letter-spacing:.5px;line-height:1.6}
.grid-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:0 10px 12px}
.grid-actions code{color:#2eef88;font-size:11px;word-break:break-all}
</style>
<div class="panel" style="margin-top:9px;" id="multiGridPanel">
<div class="panel-head">
<div class="panel-title">▦ CAMERAS &amp; DRONES</div>
<div class="live" id="multiGridCount">—</div>
</div>
<div id="multiGrid" class="multi-grid"></div>
<div class="grid-actions">
<button type="button" class="history-action-button" onclick="location.href='/setup/camera'">+ ADD CAMERA</button>
<button type="button" class="history-action-button" id="addDroneBtn">+ ADD DRONE</button>
<span id="addDroneMsg" style="font-size:10px;color:#9edfff"></span>
</div>
</div>
<script>
(function () {
    const grid = document.getElementById("multiGrid");
    const count = document.getElementById("multiGridCount");
    const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
    const tiles = {};
    let names = {main: null, drone: null}, droneSources = [];

    const whenPlayerReady = fn => window.attachLiveCamera ? fn()
        : window.addEventListener("live-player-ready", fn, {once: true});
    const setSwitch = (btn, on) => btn.setAttribute("aria-pressed", on ? "true" : "false");
    const post = (url, body) => fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})
        .then(r => r.json().then(d => { if (!r.ok || !d.ok) throw new Error(d.error || "Request failed"); return d; }));

    // Show or stop one live view. Off = no stream at all (saves CPU), not just hidden.
    function showFeed(slot, on) {
        whenPlayerReady(() => {
            const running = slot.dataset.mode !== undefined;
            if (on && !running) window.attachLiveCamera(slot);
            if (!on && running) window.detachLiveCamera(slot);
        });
    }

    // Live feed switches on the main camera and drone panels.
    function syncPrimary(key, visible) {
        const btn = document.querySelector('[data-feed-switch="' + key + '"]');
        const slot = document.querySelector('[data-live-camera="' + (key === "main" ? "" : key) + '"]')
            || (key === "main" ? document.querySelector("[data-live-camera]:not([data-live-camera='drone'])") : null);
        if (!btn || !slot) return;
        const panel = btn.closest(".panel");
        if (!panel.querySelector(".feed-off-note")) {
            const note = document.createElement("div");
            note.className = "feed-off-note";
            note.textContent = "LIVE FEED OFF — switch it on to view. Recording and AI keep running.";
            panel.querySelector(".camera-box").after(note);
        }
        setSwitch(btn, visible);
        panel.classList.toggle("feed-off", !visible);
        if (key === "drone") {
            window.droneFeedOn = visible;
            document.querySelectorAll("#droneFeedGrid .live-slot").forEach(s => showFeed(s, visible));
        } else showFeed(slot, visible);
    }
    document.querySelectorAll("[data-feed-switch]").forEach(btn => btn.addEventListener("click", async () => {
        const key = btn.dataset.feedSwitch, name = names[key];
        if (!name) return;
        const on = btn.getAttribute("aria-pressed") !== "true";
        btn.disabled = true;
        try {
            for (const n of key === "drone" && droneSources.length ? droneSources : [name])
                await post("/api/sources/" + encodeURIComponent(n) + "/feed", {visible: on});
            syncPrimary(key, on);
        }
        catch (e) { alert(e.message); }
        finally { btn.disabled = false; }
    }));

    function tileFor(c) {
        const t = document.createElement("div");
        t.className = "grid-tile";
        t.innerHTML = '<div class="live-slot" data-live-camera="' + esc(c.name) + '" title="Double-click for full screen"></div>'
            + '<div class="tile-foot"><span><i class="tile-dot"></i><span class="tile-name">'
            + (c.kind === "drone" ? "✈ " : "▣ ") + esc(c.name) + '</span> <span class="tile-fps"></span></span>'
            + '<span class="tile-actions">'
            + (c.kind === "drone" ? '<a class="tile-btn" href="/drone-control?drone=' + encodeURIComponent(c.name) + '" style="text-decoration:none">CONTROLS</a>' : '')
            + '<button type="button" class="feed-switch" data-act="feed">FEED <span class="knob"></span></button>'
            + '<button type="button" class="tile-btn" data-act="pause"></button>'
            + '<button type="button" class="tile-btn danger" data-act="remove">REMOVE</button>'
            + '</span></div>';
        const slot = t.querySelector(".live-slot");
        t.querySelector('[data-act="feed"]').addEventListener("click", async e => {
            const btn = e.currentTarget, on = btn.getAttribute("aria-pressed") !== "true";
            btn.disabled = true;
            try { await post("/api/sources/" + encodeURIComponent(c.name) + "/feed", {visible: on}); applyTile(t, {...t._c, feed_visible: on}); }
            catch (err) { alert(err.message); } finally { btn.disabled = false; }
        });
        t.querySelector('[data-act="pause"]').addEventListener("click", async e => {
            const btn = e.currentTarget, paused = !t._c.paused;
            btn.disabled = true;
            try { await post("/api/sources/" + encodeURIComponent(c.name) + "/pause", {paused}); applyTile(t, {...t._c, paused}); }
            catch (err) { alert(err.message); } finally { btn.disabled = false; }
        });
        t.querySelector('[data-act="remove"]').addEventListener("click", async e => {
            if (!confirm("Remove " + c.name + "?\n\nIt will be deleted from Frigate and its slot freed on your plan. "
                + "Recordings already saved are kept.")) return;
            const btn = e.currentTarget;
            btn.disabled = true; btn.textContent = "REMOVING…";
            try {
                const r = await fetch("/api/sources/" + encodeURIComponent(c.name), {method: "DELETE"});
                const d = await r.json();
                if (!r.ok || !d.ok) throw new Error(d.error || "Could not remove");
                window.detachLiveCamera?.(slot);
                t.remove(); delete tiles[c.name];
                document.getElementById("addDroneMsg").textContent = d.message + " Frigate is restarting.";
            } catch (err) { alert(err.message); btn.disabled = false; btn.textContent = "REMOVE"; }
        });
        return t;
    }

    function applyTile(t, c) {
        t._c = c;
        const visible = c.feed_visible !== false;
        t.classList.toggle("feed-off", !visible);
        setSwitch(t.querySelector('[data-act="feed"]'), visible);
        showFeed(t.querySelector(".live-slot"), visible);
        const dot = t.querySelector(".tile-dot");
        dot.classList.toggle("on", !!c.online && !c.paused);
        dot.classList.toggle("paused", !!c.paused);
        t.querySelector(".tile-fps").textContent = c.over_limit ? "OVER LICENCE LIMIT" : c.paused ? "STOPPED" : (c.online ? c.fps + " FPS" : "OFFLINE");
        t.title = c.over_limit ? "Switched off: your licence allows fewer cameras/drones. Remove one or upgrade the licence." : "";
        t.querySelector('[data-act="pause"]').textContent = c.paused ? "START" : "STOP";
    }

    async function refresh() {
        let data;
        try { data = await fetch("/api/cameras", {cache: "no-store"}).then(r => r.json()); } catch (e) { return; }
        const all = data.cameras || [];
        names = {main: data.main, drone: data.drone};
        for (const key of ["main", "drone"]) {
            const c = all.find(x => x.name === names[key]);
            const btn = document.querySelector('[data-feed-switch="' + key + '"]');
            const wanted = c ? c.feed_visible !== false : true;
            if (btn && (btn.dataset.synced !== "1" || (btn.getAttribute("aria-pressed") === "true") !== wanted)) {
                syncPrimary(key, wanted);
                btn.dataset.synced = "1";
            }
        }
        droneSources = all.filter(c => c.kind === "drone").map(c => c.name);
        // The main camera has its own panel and every drone is in the drone feed; the grid shows the other cameras.
        const extra = all.filter(c => !c.primary && c.kind !== "drone");
        count.textContent = all.filter(c => c.online).length + " / " + all.length + " ONLINE";
        if (!extra.length) {
            grid.innerHTML = '<div class="grid-empty">No additional cameras yet. Use <b>+ ADD CAMERA</b> below and it appears here live. '
                + 'Drones added with <b>+ ADD DRONE</b> appear in the drone live feed.</div>';
            for (const k in tiles) delete tiles[k];
            return;
        }
        grid.querySelector(".grid-empty")?.remove();
        for (const c of extra) {
            if (!tiles[c.name]) { tiles[c.name] = tileFor(c); grid.appendChild(tiles[c.name]); }
            applyTile(tiles[c.name], c);
        }
        for (const name of Object.keys(tiles)) {
            if (!extra.some(c => c.name === name)) { window.detachLiveCamera?.(tiles[name].querySelector(".live-slot")); tiles[name].remove(); delete tiles[name]; }
        }
    }

    document.getElementById("addDroneBtn").addEventListener("click", async () => {
        const btn = document.getElementById("addDroneBtn"), msg = document.getElementById("addDroneMsg");
        btn.disabled = true; msg.textContent = "Adding drone…";
        try {
            const r = await fetch("/api/setup/drone", {method: "POST"});
            const d = await r.json();
            if (!r.ok || !d.ok) throw new Error(d.error || "Could not add drone");
            msg.innerHTML = esc(d.message) + " RTMP: <code>" + esc(d.publish_url) + "</code>";
            setTimeout(refresh, 20000);  // Frigate restarts to load the new drone
        } catch (e) { msg.textContent = e.message; }
        finally { btn.disabled = false; }
    });

    refresh();
    setInterval(refresh, 10000);
})();
</script>


<div class="stats">


<div class="stat-card">

<div class="stat-title">
FACE EVENTS
</div>

<div
    id="faceCount"
    class="stat-number"
>
0
</div>

<div class="stat-sub">
SESSION
</div>

<div class="stat-line"></div>

</div>


<div class="stat-card">

<div class="stat-title">
PLATE EVENTS
</div>

<div
    id="plateCount"
    class="stat-number"
>
0
</div>

<div class="stat-sub">
SESSION
</div>

<div class="stat-line"></div>

</div>


<div class="stat-card">

<div class="stat-title">
TOTAL EVENTS
</div>

<div
    id="totalCount"
    class="stat-number"
>
0
</div>

<div class="stat-sub">
SESSION
</div>

<div class="stat-line"></div>

</div>


<div class="stat-card">

<div class="stat-title">
SYSTEM HEALTH
</div>

<div
    id="health"
    class="stat-number"
    style="color:#2fee91"
>
READY
</div>

<div class="stat-sub">
AI SERVICES
</div>

<div class="stat-line"></div>

</div>


</div>


<div
    id="historyPanel"
    class="panel history"
>

<div class="panel-head">

<div class="panel-title">
RECENT SECURITY EVENTS
</div>

<div class="event-head-actions">
<div class="live">
UNKNOWN FACE / VEHICLE CAPTURES
</div>
<button type="button" id="viewAllHistory" class="history-action-button">VIEW ALL</button>
</div>

</div>


<div class="events">

{% for event in events %}

<div class="event" id="eventCard{{ loop.index0 }}">


{% if event.image_file %}

<a
    href="/events/{{ event.image_file }}"
    target="_blank"
>

<img
    src="/events/{{ event.image_file }}"
>

</a>

{% endif %}


<div class="event-body">

<div class="event-type">
{{ event.Type }}
</div>

<div class="event-name">
{{ event.Name }}
</div>
{% if event.drone_image or event.drone_clip %}<div class="event-drone">{% if event.drone_image %}<a href="/events/{{ event.drone_image }}" target="_blank" title="The drone's view"><img src="/events/{{ event.drone_image }}" alt="Drone view"></a>{% endif %}{% if event.drone_clip %}<a class="event-clip" href="/events/{{ event.drone_clip }}" target="_blank">▶ DRONE CLIP</a>{% endif %}</div>{% endif %}

{% if 'UNKNOWN' in (event.Type|upper) or 'UNKNOWN' in (event.Name|upper) %}
<div class="unknown-event-badge">UNKNOWN DETECTION</div>
{% endif %}

<div class="event-meta">

{{ event.Date }}

&nbsp;•&nbsp;

{{ event.Time }}

{% if event.Identifier %}

<br>

{{ event.Identifier }}

{% endif %}

</div>

<button
    type="button"
    class="delete-event-button"
    data-event-index="{{ loop.index0 }}"
    data-event-key="{{ event.event_key }}"
>
DELETE EVENT
</button>

</div>

</div>

{% endfor %}

</div>

</div>


</div>


<!-- =======================================================
     FULL EVENT HISTORY
     ======================================================= -->

<div id="eventHistoryOverlay" class="history-overlay">
<div class="history-window">

<div class="history-window-head">
<div>
<div class="history-window-title">EVENT HISTORY</div>
<div class="history-window-sub">ALL SAVED SECURITY EVENTS • UNKNOWN FACE / VEHICLE CAPTURES INCLUDED</div>
</div>

<div class="event-head-actions">
<button type="button" id="clearAllEvents" class="history-action-button danger">CLEAR ALL</button>
<button type="button" id="closeEventHistory" class="history-action-button">CLOSE</button>
</div>
</div>

<div class="full-history-events">
{% if history_events %}
{% for event in history_events %}
<div class="event history-event-card">

{% if event.image_file %}
<a href="/events/{{ event.image_file }}" target="_blank">
<img src="/events/{{ event.image_file }}">
</a>
{% endif %}

<div class="event-body">
<div class="event-type">{{ event.Type }}</div>
<div class="event-name">{{ event.Name }}</div>
{% if event.drone_image or event.drone_clip %}<div class="event-drone">{% if event.drone_image %}<a href="/events/{{ event.drone_image }}" target="_blank" title="The drone's view"><img src="/events/{{ event.drone_image }}" alt="Drone view"></a>{% endif %}{% if event.drone_clip %}<a class="event-clip" href="/events/{{ event.drone_clip }}" target="_blank">▶ DRONE CLIP</a>{% endif %}</div>{% endif %}

{% if 'UNKNOWN' in (event.Type|upper) or 'UNKNOWN' in (event.Name|upper) %}
<div class="unknown-event-badge">UNKNOWN DETECTION</div>
{% endif %}

<div class="event-meta">
{{ event.Date }} &nbsp;•&nbsp; {{ event.Time }}
{% if event.Identifier %}
<br>{{ event.Identifier }}
{% endif %}
</div>

<button type="button" class="delete-event-button" data-event-index="{{ loop.index0 }}" data-event-key="{{ event.event_key }}">DELETE EVENT</button>
</div>
</div>
{% endfor %}
{% else %}
<div class="waiting" style="grid-column:1 / -1">NO SECURITY EVENTS SAVED</div>
{% endif %}
</div>

</div>
</div>


<!-- =======================================================
     RIGHT AI
     ======================================================= -->

<div class="right-column">


<div class="panel">

<div class="panel-head">

<div class="panel-title">
AI IDENTIFICATION
</div>

<div class="live">
REAL-TIME
</div>

</div>


<div class="ai-body">


<!-- FACE SCANNER -->

<div class="scanner-row">


<div class="scanner">

<div class="scanner-label">
FACE BIOMETRIC
</div>

<div class="ring ring1"></div>
<div class="ring ring2"></div>
<div class="ring ring3"></div>

<div class="face"></div>

<div class="scanline"></div>

</div>


<div class="scan-info">

<div class="scan-title">
CURRENT STATUS
</div>

<div class="scan-status">

<div class="shield">
✓
</div>

<div id="faceStatus">
SCANNING
</div>

</div>


<div class="scan-detail">

DETECTED BY

<br>

FACE AI

<br><br>

LAST UPDATE

<br>

<span id="faceUpdate">
--
</span>

</div>

</div>


</div>


<!-- VEHICLE SCANNER -->

<div class="scanner-row">


<div class="scanner">

<div class="scanner-label">
VEHICLE / LPR
</div>

<div class="ring ring1"></div>
<div class="ring ring2"></div>
<div class="ring ring3"></div>

<div class="car">

<div class="light left-light"></div>
<div class="light right-light"></div>

</div>

<div class="scanline"></div>

</div>


<div class="scan-info">

<div class="scan-title">
VEHICLE STATUS
</div>

<div class="scan-status">

<div class="shield">
✓
</div>

<div id="vehicleStatus">
SCANNING
</div>

</div>


<div class="scan-detail">

PLATE READ

<div
    id="scannerPlate"
    class="scan-plate"
>
------
</div>

<br>

DETECTED BY

<br>

LPR AI

</div>

</div>


</div>


<!-- SECURITY CONTROLS -->

<div class="rec-title">
AI SECURITY CONTROLS
</div>


<div id="cloudPlanCard" style="grid-column:1 / -1;border:1px solid #164b67;padding:10px;margin-bottom:8px;font-size:10px;color:#8ba9b8;background:rgba(2,15,24,.72);">
  <div style="display:flex;justify-content:space-between"><span>CLOUD PLAN</span><strong id="cloudPlanName" style="color:#34d9ff">CHECKING...</strong></div>
  <div id="cloudPlanUsage" style="margin-top:6px;color:#d8f4ff">Loading plan limits...</div>
</div>

<div class="security-controls">

<button
    type="button"
    id="openFaceEnroll"
    class="security-button face-button"
>
＋ ADD FACE
</button>


<button
    type="button"
    id="openVehicleEnroll"
    class="security-button vehicle-button"
>
＋ ADD VEHICLE
</button>


<button
    type="button"
    id="openFaceLibrary"
    class="security-button"
>
FACE LIBRARY
</button>


<button
    type="button"
    id="openVehicleLibrary"
    class="security-button"
>
KNOWN VEHICLES
</button>


<button
    type="button"
    id="goHistory"
    class="security-button"
    style="grid-column:1 / -1"
>
EVENT HISTORY
</button>


<button
    type="button"
    id="cameraToggle"
    class="security-button"
    style="grid-column:1 / -1; border-color:#9a6200; color:#ffb23c;"
>
CAMERA AI • CHECKING...
</button>

<button
    type="button"
    id="objectAiToggle"
    class="security-button"
    style="grid-column:1 / -1; border-color:#9a6200; color:#ffb23c;"
>
OBJECT AI • CHECKING...
</button>
<div id="objectAiPanel" style="grid-column:1 / -1; border:1px solid #164b67; padding:9px; font-size:10px; color:#8ba9b8; background:rgba(2,15,24,.72);">
  <div style="display:flex;justify-content:space-between"><span>OBJECTS DETECTED</span><span id="objectAiCount">0</span></div>
  <div id="objectAiList" style="margin-top:7px;color:#d8f4ff;line-height:1.6">WAITING FOR OBJECTS...</div>
</div>

<button
    type="button"
    id="droneToggle"
    class="security-button"
    style="grid-column:1 / -1; border-color:#9a6200; color:#ffb23c;"
>
DRONE AI • CHECKING...
</button>

<button type="button" id="droneTrackingToggle" class="security-button" style="grid-column:1 / -1; border-color:#385e74; color:#7edcff;">
DRONE TRACKING ASSIST • OFF
</button>
<div id="droneTrackingPanel" style="grid-column:1 / -1; border:1px solid #164b67; padding:10px; font-size:10px; color:#8ba9b8; background:rgba(2,15,24,.72);">
  <div style="display:flex; justify-content:space-between;"><span>TRACK TARGET</span><span id="droneTrackState">OFF</span></div>
  <div id="droneTrackLabel" style="margin-top:8px; font-size:13px; color:#d8f4ff;">NO TARGET</div>
  <div id="droneTrackDirection" style="margin-top:5px; font-size:18px; font-weight:bold; color:#34d9ff;">WAITING</div>
  <div style="margin-top:6px; font-size:8px; color:#617f8f;">MANUAL FLIGHT GUIDANCE — KEEP THE TARGET CENTERED</div>
</div>

<button
    type="button"
    id="voiceControlButton"
    class="security-button voice-button"
>
<span class="voice-bars">
<span></span><span></span><span></span><span></span><span></span>
</span>
VOICE COMMAND
</button>


<div class="voice-console">
<div class="voice-console-head">
<span>VOICE INTERACTION</span>
<span id="voiceState" class="voice-state">READY</span>
</div>
<div id="voiceTranscript" class="voice-transcript">
Say “add face”, “add face John Smith”, “start scan”, or “system status”.
</div>
<div class="voice-hint">
Commands: Add Face • Start Scan • Cancel Scan • Add Vehicle • Face Library • Known Vehicles • Event History • System Status • What Did You Detect • Close
</div>
</div>


</div>


<div class="rec-title">
CURRENT RECOGNITION
</div>


<div id="recognition">

<div class="waiting">

AI scanners active —
waiting for detection...

</div>

</div>


</div>

</div>


</div>


</div>


<!-- =======================================================
     FACE ENROLLMENT MODAL
     ======================================================= -->

<div
    id="faceEnrollOverlay"
    class="enroll-overlay"
>


<div class="enroll-window">


<div class="enroll-header">

<div>
SECURE BIOMETRIC FACE ENROLLMENT
</div>

<button
    type="button"
    id="closeFaceEnroll"
    class="close-enroll"
>
×
</button>

</div>


<div class="enroll-content">


<!-- LIVE BIOMETRIC VIEW -->

<div
    id="enrollScanner"
    class="enroll-scanner"
>

<img
    id="enrollCameraFeed"
    data-src="/video_feed"
    class="enroll-live-camera"
    alt=""
>

<div class="enroll-blue-filter"></div>

<div class="enroll-grid"></div>

<div class="enroll-ring ring-a"></div>
<div class="enroll-ring ring-b"></div>
<div class="enroll-ring ring-c"></div>


<div class="face-target">

<div class="face-landmark lm1"></div>
<div class="face-landmark lm2"></div>
<div class="face-landmark lm3"></div>
<div class="face-landmark lm4"></div>
<div class="face-landmark lm5"></div>

</div>


<div class="enroll-scan-line"></div>


<div class="scanner-corner ec1"></div>
<div class="scanner-corner ec2"></div>
<div class="scanner-corner ec3"></div>
<div class="scanner-corner ec4"></div>


<div
    id="enrollScannerText"
    class="scanner-message"
>
READY FOR BIOMETRIC CAPTURE
</div>


</div>


<!-- ENROLLMENT CONTROLS -->

<div class="enroll-panel">


<div class="enroll-label">
PERSON NAME
</div>


<input
    id="faceName"
    class="enroll-input"
    type="text"
    autocomplete="off"
    placeholder="Enter person's name"
>

<div class="enroll-label" style="margin-top:12px;">CAPTURE SOURCE</div>
<select id="faceEnrollSource" class="enroll-input">
    <option value="camera">MAIN CAMERA</option>
    <option value="drone">DRONE</option>
</select>

<div class="security-note">

SECURE ENROLLMENT PROCEDURE

<br><br>

• Only one person should be visible.

<br>

• Keep the face inside the blue frame.

<br>

• Good lighting is required.

<br>

• Hold still during each capture.

<br>

• The system captures 3 facial samples.

<br><br>

The movement prompts improve the
variety of stored samples. They are
guidance prompts rather than certified
liveness detection.

</div>


<button
    type="button"
    id="startFaceEnrollment"
    class="start-scan-button"
>
START BIOMETRIC SCAN
</button>


<button
    type="button"
    id="cancelFaceEnrollment"
    class="cancel-scan-button"
>
CANCEL SCAN
</button>


<div class="progress-area">


<div class="progress-header">

<span id="enrollStage">
READY
</span>

<span id="enrollPercent">
0%
</span>

</div>


<div class="progress-track">

<div
    id="enrollProgress"
    class="progress-fill"
></div>

</div>


<div class="sample-dots">

<div
    id="sample1"
    class="sample-dot"
></div>

<div
    id="sample2"
    class="sample-dot"
></div>

<div
    id="sample3"
    class="sample-dot"
></div>

<div id="sample4" class="sample-dot" style="display:none"></div>
<div id="sample5" class="sample-dot" style="display:none"></div>

</div>


<div
    id="enrollMessage"
    class="enroll-message"
>
Position the person's face
inside the scanner.
</div>


</div>


</div>


</div>

</div>

</div>


<!-- =======================================================
     VEHICLE ENROLLMENT MODAL
     ======================================================= -->

<div
    id="vehicleEnrollOverlay"
    class="enroll-overlay"
>


<div class="enroll-window small-window">


<div class="enroll-header">

<div>
VEHICLE / LPR ENROLLMENT
</div>

<button
    id="closeVehicleEnroll"
    class="close-enroll"
    type="button"
>
×
</button>

</div>


<div class="vehicle-enroll-body">


<div class="mini-car-scanner">

<div class="mini-radar"></div>

<div class="mini-car">
🚙
</div>

<div class="vehicle-sweep"></div>

</div>


<div>


<div class="enroll-label">
VEHICLE NAME
</div>


<input
    id="newVehicleName"
    class="enroll-input"
    type="text"
    placeholder="Example: Tony F150"
>


<div
    class="enroll-label vehicle-label-space"
>
LICENSE PLATE
</div>


<input
    id="newVehiclePlate"
    class="enroll-input plate-input"
    type="text"
    placeholder="ABC123 — leave blank to use latest LPR"
>

<div class="enroll-label" style="margin-top:12px;">DETECTION SOURCE</div>
<select id="vehicleEnrollSource" class="enroll-input">
    <option value="camera">MAIN CAMERA</option>
    <option value="drone">DRONE</option>
</select>

<button
    id="saveVehicle"
    type="button"
    class="start-scan-button"
>
REGISTER VEHICLE
</button>


<div
    id="vehicleSaveMessage"
    class="enroll-message"
></div>


</div>


</div>

</div>

</div>


<!-- =======================================================
     FACE LIBRARY MODAL
     ======================================================= -->

<div
    id="faceLibraryOverlay"
    class="enroll-overlay"
>


<div class="enroll-window small-window">


<div class="enroll-header">

<div>
FACE LIBRARY
</div>

<button
    id="closeFaceLibrary"
    class="close-enroll"
    type="button"
>
×
</button>

</div>


<div class="simple-body">

<div
    id="faceLibraryContent"
    class="library-grid"
>

<div class="waiting">
Loading face library...
</div>

</div>

</div>


</div>

</div>


<!-- =======================================================
     VEHICLE LIBRARY MODAL
     ======================================================= -->

<div
    id="vehicleLibraryOverlay"
    class="enroll-overlay"
>


<div class="enroll-window small-window">


<div class="enroll-header">

<div>
KNOWN VEHICLES
</div>

<button
    id="closeVehicleLibrary"
    class="close-enroll"
    type="button"
>
×
</button>

</div>


<div class="simple-body">

<div
    id="vehicleLibraryContent"
    class="library-grid"
>

<div class="waiting">
Loading vehicles...
</div>

</div>

</div>


</div>

</div>


<script>

/* ==========================================================
   CLOCK
   ========================================================== */

function updateClock() {

    const now =
        new Date();

    document.getElementById(
        "clock"
    ).innerText =
        now.toLocaleTimeString();

    document.getElementById(
        "date"
    ).innerText =
        now.toLocaleDateString();
}


setInterval(
    updateClock,
    1000
);

updateClock();


/* ==========================================================
   MATRIX RUNNING NUMBERS
   ========================================================== */

const canvas =
    document.getElementById(
        "matrixCanvas"
    );

const ctx =
    canvas.getContext(
        "2d"
    );

const fontSize = 13;

let drops = [];


function resizeMatrix() {

    const parent =
        canvas.parentElement;

    canvas.width =
        parent.clientWidth;

    canvas.height =
        parent.clientHeight;

    const columns =
        Math.floor(
            canvas.width
            / fontSize
        );

    drops =
        new Array(columns)
        .fill(1)
        .map(
            () =>
                Math.floor(
                    Math.random()
                    * canvas.height
                    / fontSize
                )
        );
}


function drawMatrix() {

    ctx.fillStyle =
        "rgba(0,8,5,0.12)";

    ctx.fillRect(
        0,
        0,
        canvas.width,
        canvas.height
    );

    ctx.font =
        fontSize
        + "px Consolas, monospace";


    for (
        let i = 0;
        i < drops.length;
        i++
    ) {

        const random =
            Math.random();

        let character;

        if (random < .40) {

            character =
                Math.floor(
                    Math.random()
                    * 10
                );

        }

        else if (random < .80) {

            character =
                Math.random() > .5
                ? "1"
                : "0";

        }

        else {

            character =
                String.fromCharCode(
                    65
                    +
                    Math.floor(
                        Math.random()
                        * 6
                    )
                );
        }


        if (
            Math.random()
            > .93
        ) {

            ctx.fillStyle =
                "#9affad";

        }

        else {

            ctx.fillStyle =
                "#12c755";
        }


        ctx.fillText(
            character,
            i * fontSize,
            drops[i] * fontSize
        );


        if (
            drops[i] * fontSize
            > canvas.height
            &&
            Math.random() > .97
        ) {

            drops[i] = 0;

        }

        else {

            drops[i] += .65;
        }
    }
}


resizeMatrix();

window.addEventListener(
    "resize",
    resizeMatrix
);

setInterval(
    drawMatrix,
    110
);


/* ==========================================================
   STATUS
   ========================================================== */

let lastDashboardStatus = null;
let lastDetectedFace = "";
let lastDetectedVehicle = "";
let lastDetectedPlate = "";

async function refreshStatus() {

    try {

        const response =
            await fetch(
                "/api/status"
            );

        const d =
            await response.json();

        lastDashboardStatus = d;
        if (d.face) lastDetectedFace = d.face;
        if (d.vehicle && !d.unknown_vehicle) lastDetectedVehicle = d.vehicle;
        if (d.plate && !d.unknown_vehicle) lastDetectedPlate = d.plate;


        document.getElementById(
            "faceCount"
        ).innerText =
            d.face_count;


        document.getElementById(
            "plateCount"
        ).innerText =
            d.plate_count;


        document.getElementById(
            "totalCount"
        ).innerText =
            d.total_events;


        document.getElementById(
            "leftCamera"
        ).innerText =
            d.camera
            ? "ONLINE"
            : "OFFLINE";


        document.getElementById(
            "leftMqtt"
        ).innerText =
            d.mqtt
            ? "CONNECTED"
            : "OFFLINE";


        document.getElementById(
            "topCamera"
        ).innerHTML =
            d.camera

            ? '<span class="dot"></span>ONLINE'

            : '<span class="dot" style="background:#ff4558;box-shadow:0 0 10px #ff4558"></span>OFFLINE';


        document.getElementById(
            "topMqtt"
        ).innerHTML =
            d.mqtt

            ? '<span class="dot"></span>CONNECTED'

            : '<span class="dot" style="background:#ff4558;box-shadow:0 0 10px #ff4558"></span>OFFLINE';


        const alertActive =
            d.unknown_face
            ||
            d.unknown_vehicle;


        document.getElementById(
            "topSystem"
        ).innerHTML =
            alertActive

            ? '<span class="dot" style="background:#ff4558;box-shadow:0 0 10px #ff4558"></span>ALERT'

            : '<span class="dot"></span>PROTECTED';


        document.getElementById(
            "health"
        ).innerText =
            d.camera
            &&
            d.mqtt

            ? "READY"

            : "CHECK";


        /* FACE */

        const faceStatus =
            document.getElementById(
                "faceStatus"
            );


        if (d.unknown_face) {

            faceStatus.innerText =
                "UNKNOWN";

            faceStatus.style.color =
                "#ff5364";

        }

        else if (d.face) {

            faceStatus.innerText =
                "AUTHORIZED";

            faceStatus.style.color =
                "#2eee91";

        }

        else {

            faceStatus.innerText =
                "SCANNING";

            faceStatus.style.color =
                "#39c8ff";
        }


        /* VEHICLE */

        const vehicleStatus =
            document.getElementById(
                "vehicleStatus"
            );


        if (d.unknown_vehicle) {

            vehicleStatus.innerText =
                "UNKNOWN";

            vehicleStatus.style.color =
                "#ffb62b";

        }

        else if (d.plate) {

            vehicleStatus.innerText =
                "AUTHORIZED";

            vehicleStatus.style.color =
                "#2eee91";

        }

        else {

            vehicleStatus.innerText =
                "SCANNING";

            vehicleStatus.style.color =
                "#39c8ff";
        }


        document.getElementById(
            "scannerPlate"
        ).innerText =
            d.plate
            ||
            "------";


        /* CURRENT RECOGNITION — MULTI TARGET */

        let html = "";

        const activeFaces = Array.isArray(d.active_faces) ? d.active_faces : [];
        const activeVehicles = Array.isArray(d.active_vehicles) ? d.active_vehicles : [];

        activeFaces.forEach(faceItem => {
            const known = !!faceItem.known;
            const label = faceItem.label || (known ? "KNOWN PERSON" : "PERSON");

            if (known) {
                html += `
                <div class="rec-card person-card">
                    <div class="rec-row">
                        <div class="rec-icon">◉</div>
                        <div class="rec-info">
                            <div class="rec-label">IDENTITY VERIFIED</div>
                            <div class="rec-name">${label}</div>
                            <div class="rec-sub">Authorized Person</div>
                        </div>
                        <div class="check">✓</div>
                    </div>
                </div>`;
            } else {
                html += `
                <div class="rec-card unknown-person">
                    <div class="rec-row">
                        <div class="rec-icon">!</div>
                        <div class="rec-info">
                            <div class="rec-label">${label === "PERSON" ? "PERSON DETECTED" : "UNKNOWN PERSON ALERT"}</div>
                            <div class="rec-sub">${label === "PERSON" ? "Face identification pending" : "Identity not recognized"}</div>
                        </div>
                    </div>
                </div>`;
            }
        });

        activeVehicles.forEach(vehicleItem => {
            const known = !!vehicleItem.known;
            const label = vehicleItem.label || (known ? "KNOWN VEHICLE" : "VEHICLE");
            const plate = vehicleItem.plate || "";

            if (known) {
                html += `
                <div class="rec-card vehicle-card">
                    <div class="rec-row">
                        <div class="rec-icon">🚙</div>
                        <div class="rec-info">
                            <div class="rec-label">VEHICLE AUTHORIZED</div>
                            <div class="rec-name">${label}</div>
                            <div class="rec-sub">${plate ? "Plate: " + plate : "Vehicle recognized"}</div>
                        </div>
                        ${plate ? `<div class="plate-box">${plate}</div>` : ""}
                        <div class="check">✓</div>
                    </div>
                </div>`;
            } else {
                html += `
                <div class="rec-card unknown-vehicle">
                    <div class="rec-row">
                        <div class="rec-icon">!</div>
                        <div class="rec-info">
                            <div class="rec-label">${plate ? "UNKNOWN VEHICLE ALERT" : "VEHICLE DETECTED"}</div>
                            <div class="rec-sub">${plate ? "Unregistered plate: " + plate : "Plate identification pending"}</div>
                        </div>
                    </div>
                </div>`;
            }
        });

        // Backward-compatible fallback if an older state reaches the browser.
        if (!activeFaces.length && d.face) {
            html += `
            <div class="rec-card person-card">
                <div class="rec-row">
                    <div class="rec-icon">◉</div>
                    <div class="rec-info">
                        <div class="rec-label">IDENTITY VERIFIED</div>
                        <div class="rec-name">${d.face}</div>
                        <div class="rec-sub">Authorized Person</div>
                    </div>
                    <div class="check">✓</div>
                </div>
            </div>`;
        }

        if (!activeVehicles.length && d.plate && !d.unknown_vehicle) {
            html += `
            <div class="rec-card vehicle-card">
                <div class="rec-row">
                    <div class="rec-icon">🚙</div>
                    <div class="rec-info">
                        <div class="rec-label">VEHICLE AUTHORIZED</div>
                        <div class="rec-name">${d.vehicle}</div>
                        <div class="rec-sub">Plate: ${d.plate}</div>
                    </div>
                    <div class="plate-box">${d.plate}</div>
                    <div class="check">✓</div>
                </div>
            </div>`;
        }


        if (!html) {

            html = `

            <div class="waiting">
                AI scanners active —
                waiting for detection...
            </div>

            `;
        }


        document.getElementById(
            "recognition"
        ).innerHTML =
            html;


        if (
            d.face
            ||
            d.unknown_face
        ) {

            document.getElementById(
                "faceUpdate"
            ).innerText =
                new Date()
                .toLocaleTimeString();
        }


    }

    catch (error) {

        console.log(
            "Dashboard status error:",
            error
        );
    }
}


setInterval(
    refreshStatus,
    750
);

refreshStatus();


/* ==========================================================
   VOICE INTERACTION
   ========================================================== */

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let voiceRecognition = null;
let voiceListening = false;
let voicePendingAction = "";

const voiceButton = document.getElementById("voiceControlButton");
const voiceState = document.getElementById("voiceState");
const voiceTranscript = document.getElementById("voiceTranscript");

function setVoiceUI(state, text = "") {
    if (voiceState) {
        voiceState.innerText = state;
        voiceState.classList.toggle("active", state === "LISTENING");
    }
    if (voiceButton) {
        voiceButton.classList.toggle("listening", state === "LISTENING");
        voiceButton.innerHTML = state === "LISTENING"
            ? '<span class="voice-bars"><span></span><span></span><span></span><span></span><span></span></span>LISTENING...'
            : '<span class="voice-bars"><span></span><span></span><span></span><span></span><span></span></span>VOICE COMMAND';
    }
    if (text && voiceTranscript) voiceTranscript.innerText = text;
}

function speakDashboard(text, thenListen = false) {
    if (!("speechSynthesis" in window)) {
        if (thenListen) setTimeout(startVoiceListening, 250);
        return;
    }
    try {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 0.98;
        utterance.pitch = 1.0;
        utterance.volume = 0.9;
        utterance.onend = () => {
            if (thenListen) setTimeout(startVoiceListening, 300);
        };
        window.speechSynthesis.speak(utterance);
    } catch (error) {
        if (thenListen) setTimeout(startVoiceListening, 300);
    }
}

function openFaceEnrollmentByVoice() {
    document.getElementById("faceEnrollOverlay").classList.add("open");
    setTimeout(() => document.getElementById("faceName").focus(), 100);
}

function openVehicleEnrollmentByVoice() {
    document.getElementById("vehicleEnrollOverlay").classList.add("open");
    setTimeout(() => document.getElementById("newVehicleName").focus(), 100);
}

function closeVoiceTarget() {
    document.querySelectorAll(".enroll-overlay.open").forEach(el => el.classList.remove("open"));
    stopBiometricSound();
    voicePendingAction = "";
    speakDashboard("Closed.");
}

function normalizeSpokenPlate(text) {
    return text.toUpperCase().replace(/\b(DASH|HYPHEN|SPACE)\b/g, "").replace(/[^A-Z0-9]/g, "");
}

function titleCaseVoiceName(text) {
    return text.trim().replace(/\s+/g, " ").split(" ")
        .map(word => word ? word.charAt(0).toUpperCase() + word.slice(1).toLowerCase() : "")
        .join(" ");
}

async function handleVoiceCommand(rawTranscript) {
    const transcript = rawTranscript.trim();
    const command = transcript.toLowerCase().replace(/[.,!?]/g, "").trim();
    if (!command) return;

    setVoiceUI("PROCESSING", 'Heard: “' + transcript + '”');

    if (voicePendingAction === "face_name") {
        const name = titleCaseVoiceName(transcript);
        document.getElementById("faceName").value = name;
        openFaceEnrollmentByVoice();
        voicePendingAction = "";
        speakDashboard("Name set to " + name + ". Say start scan when ready.");
        setVoiceUI("READY", "Person name: " + name + ". Say “start scan” when ready.");
        return;
    }

    if (voicePendingAction === "vehicle_name") {
        const vehicleName = transcript.trim();
        document.getElementById("newVehicleName").value = vehicleName;
        openVehicleEnrollmentByVoice();
        voicePendingAction = "vehicle_plate";
        speakDashboard("Vehicle name set to " + vehicleName + ". What is the license plate?", true);
        return;
    }

    if (voicePendingAction === "vehicle_plate") {
        const plate = normalizeSpokenPlate(transcript);
        document.getElementById("newVehiclePlate").value = plate;
        voicePendingAction = "";
        speakDashboard("Plate set to " + plate.split("").join(" ") + ". Say register vehicle to save it.");
        setVoiceUI("READY", "Plate: " + plate + ". Say “register vehicle” to save.");
        return;
    }

    let match = transcript.match(/^\s*(?:add|register|enroll)\s+(?:face|person)\s+(.+)$/i);
    if (match && match[1].trim()) {
        const name = titleCaseVoiceName(match[1]);
        document.getElementById("faceName").value = name;
        openFaceEnrollmentByVoice();
        speakDashboard("Face enrollment opened for " + name + ". Say start scan when ready.");
        setVoiceUI("READY", "Enrollment ready for " + name + ".");
        return;
    }

    if (/^(add|register|enroll) (a )?(face|person)$/.test(command)) {
        openFaceEnrollmentByVoice();
        voicePendingAction = "face_name";
        speakDashboard("Face enrollment ready. What is the person's name?", true);
        return;
    }

    if (/^(start|begin) (biometric )?(face )?scan$/.test(command) || command === "start scan") {
        openFaceEnrollmentByVoice();
        const name = document.getElementById("faceName").value.trim();
        if (!name) {
            voicePendingAction = "face_name";
            speakDashboard("I need the person's name first. What is the name?", true);
            return;
        }
        speakDashboard("Starting biometric scan for " + name + ".");
        document.getElementById("startFaceEnrollment").click();
        setVoiceUI("READY", "Biometric scan started for " + name + ".");
        return;
    }

    if (/^(cancel|stop) (the )?(biometric )?(face )?scan$/.test(command) || command === "cancel scan") {
        document.getElementById("cancelFaceEnrollment").click();
        voicePendingAction = "";
        speakDashboard("Biometric scan cancelled.");
        setVoiceUI("READY", "Biometric scan cancelled.");
        return;
    }

    match = transcript.match(/^\s*(?:add|register)\s+vehicle\s+(.+?)\s+plate\s+([A-Za-z0-9\s-]+)$/i);
    if (match) {
        const vehicleName = match[1].trim();
        const plate = normalizeSpokenPlate(match[2]);
        document.getElementById("newVehicleName").value = vehicleName;
        document.getElementById("newVehiclePlate").value = plate;
        openVehicleEnrollmentByVoice();
        speakDashboard("Vehicle information entered. Say register vehicle to save it.");
        setVoiceUI("READY", vehicleName + " • " + plate);
        return;
    }

    if (/^(add|register) (a )?vehicle$/.test(command)) {
        openVehicleEnrollmentByVoice();
        voicePendingAction = "vehicle_name";
        speakDashboard("Vehicle enrollment ready. What is the vehicle name?", true);
        return;
    }

    if (command === "register vehicle" || command === "save vehicle") {
        const vehicle = document.getElementById("newVehicleName").value.trim();
        const plate = document.getElementById("newVehiclePlate").value.trim();
        if (!vehicle) {
            voicePendingAction = "vehicle_name";
            speakDashboard("I need the vehicle name first. What is the vehicle name?", true);
            return;
        }
        if (!plate) {
            voicePendingAction = "vehicle_plate";
            speakDashboard("I need the license plate. What is the plate?", true);
            return;
        }
        document.getElementById("saveVehicle").click();
        speakDashboard("Registering " + vehicle + " with plate " + plate.split("").join(" ") + ".");
        setVoiceUI("READY", "Registering vehicle " + vehicle + " • " + plate);
        return;
    }

    if (command.includes("face library") || command === "show faces") {
        document.getElementById("openFaceLibrary").click();
        speakDashboard("Opening face library.");
        setVoiceUI("READY", "Face library opened.");
        return;
    }

    if (command.includes("known vehicles") || command.includes("vehicle library")) {
        document.getElementById("openVehicleLibrary").click();
        speakDashboard("Opening known vehicles.");
        setVoiceUI("READY", "Known vehicles opened.");
        return;
    }

    if (command.includes("event history") || command === "show history" || command === "history") {
        document.getElementById("goHistory").click();
        speakDashboard("Showing event history.");
        setVoiceUI("READY", "Event history displayed.");
        return;
    }

    if (command === "system status" || command === "security status" || command === "status") {
        const d = lastDashboardStatus;
        if (!d) {
            speakDashboard("System status is not available yet.");
            return;
        }
        const cameraText = d.camera ? "camera online" : "camera offline";
        const mqttText = d.mqtt ? "M Q T T connected" : "M Q T T offline";
        const alertText = (d.unknown_face || d.unknown_vehicle)
            ? "Attention. An unknown detection is active."
            : "No active unknown alerts.";
        const text = "System status. " + cameraText + ". " + mqttText + ". " + alertText;
        speakDashboard(text);
        setVoiceUI("READY", text);
        return;
    }

    if (command.includes("what did you detect") || command.includes("last detection") || command.includes("who did you see")) {
        const pieces = [];
        if (lastDetectedFace) pieces.push("Last recognized person was " + lastDetectedFace);
        if (lastDetectedVehicle) {
            let vehicleText = "last recognized vehicle was " + lastDetectedVehicle;
            if (lastDetectedPlate) vehicleText += " with plate " + lastDetectedPlate.split("").join(" ");
            pieces.push(vehicleText);
        }
        const text = pieces.length ? pieces.join(". ") + "." : "I do not have a recent recognized person or vehicle yet.";
        speakDashboard(text);
        setVoiceUI("READY", text);
        return;
    }

    if (command === "close" || command === "close window" || command === "go back") {
        closeVoiceTarget();
        setVoiceUI("READY", "Closed.");
        return;
    }

    if (command === "help" || command === "voice help" || command === "commands") {
        const help = "You can say add face, add face followed by a name, start scan, cancel scan, add vehicle, face library, known vehicles, event history, system status, what did you detect, or close.";
        speakDashboard(help);
        setVoiceUI("READY", help);
        return;
    }

    if (command.includes("delete event")) {
        const text = "For safety, voice control does not delete events. Please use the delete event button and confirm it on screen.";
        speakDashboard(text);
        setVoiceUI("READY", text);
        return;
    }

    const notUnderstood = "Command not recognized. Say voice help to hear available commands.";
    speakDashboard(notUnderstood);
    setVoiceUI("READY", notUnderstood);
}

function setupVoiceRecognition() {
    if (!SpeechRecognition) {
        setVoiceUI("UNAVAILABLE", "Voice recognition is not supported by this browser. Use Microsoft Edge or Google Chrome and allow microphone access.");
        if (voiceButton) voiceButton.disabled = true;
        return;
    }

    voiceRecognition = new SpeechRecognition();
    voiceRecognition.lang = "en-CA";
    voiceRecognition.continuous = false;
    voiceRecognition.interimResults = true;
    voiceRecognition.maxAlternatives = 1;

    voiceRecognition.onstart = () => {
        voiceListening = true;
        setVoiceUI("LISTENING", "Listening for a command...");
    };

    voiceRecognition.onresult = event => {
        let interim = "";
        let finalText = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
            const text = event.results[i][0].transcript;
            if (event.results[i].isFinal) finalText += text;
            else interim += text;
        }
        if (interim) setVoiceUI("LISTENING", interim);
        if (finalText.trim()) handleVoiceCommand(finalText.trim());
    };

    voiceRecognition.onerror = event => {
        voiceListening = false;
        if (event.error === "not-allowed" || event.error === "service-not-allowed") {
            setVoiceUI("MIC BLOCKED", "Microphone permission is blocked. Allow microphone access for this dashboard, then try again.");
        } else if (event.error === "no-speech") {
            setVoiceUI("READY", "No speech heard. Press Voice Command and try again.");
        } else if (event.error !== "aborted") {
            setVoiceUI("ERROR", "Voice recognition error: " + event.error);
        }
    };

    voiceRecognition.onend = () => {
        voiceListening = false;
        if (voiceState && voiceState.innerText === "LISTENING") {
            setVoiceUI("READY", voiceTranscript ? voiceTranscript.innerText : "Ready.");
        }
    };
}

function startVoiceListening() {
    if (!voiceRecognition) return;
    try {
        if ("speechSynthesis" in window) window.speechSynthesis.cancel();
        if (voiceListening) voiceRecognition.stop();
        setTimeout(() => {
            try { voiceRecognition.start(); }
            catch (error) { }
        }, voiceListening ? 180 : 0);
    } catch (error) {
        setVoiceUI("ERROR", "Could not start microphone. Check browser microphone permission.");
    }
}

setupVoiceRecognition();

if (voiceButton) {
    voiceButton.addEventListener("click", () => {
        if (!voiceRecognition) return;
        if (voiceListening) {
            voiceRecognition.stop();
            setVoiceUI("READY", "Voice listening stopped.");
        } else {
            startVoiceListening();
        }
    });
}

document.addEventListener("keydown", event => {
    const tag = (event.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || event.target.isContentEditable) return;
    if (event.key.toLowerCase() === "v") {
        event.preventDefault();
        startVoiceListening();
    }
});


/* ==========================================================
   MODALS
   ========================================================== */

const faceOverlay =
    document.getElementById(
        "faceEnrollOverlay"
    );

const vehicleOverlay =
    document.getElementById(
        "vehicleEnrollOverlay"
    );

const faceLibraryOverlay =
    document.getElementById(
        "faceLibraryOverlay"
    );

const vehicleLibraryOverlay =
    document.getElementById(
        "vehicleLibraryOverlay"
    );


document.getElementById(
    "openFaceEnroll"
).addEventListener(
    "click",
    () => {

        faceOverlay
            .classList
            .add("open");

        setTimeout(
            () => {

                document.getElementById(
                    "faceName"
                ).focus();

            },
            100
        );
    }
);


document.getElementById(
    "closeFaceEnroll"
).addEventListener(
    "click",
    () => {

        faceOverlay
            .classList
            .remove("open");

        stopBiometricSound();
    }
);


document.getElementById(
    "openVehicleEnroll"
).addEventListener(
    "click",
    () => {

        vehicleOverlay
            .classList
            .add("open");
    }
);


document.getElementById(
    "closeVehicleEnroll"
).addEventListener(
    "click",
    () => {

        vehicleOverlay
            .classList
            .remove("open");
    }
);


document.getElementById(
    "closeFaceLibrary"
).addEventListener(
    "click",
    () => {

        faceLibraryOverlay
            .classList
            .remove("open");
    }
);


document.getElementById(
    "closeVehicleLibrary"
).addEventListener(
    "click",
    () => {

        vehicleLibraryOverlay
            .classList
            .remove("open");
    }
);



/* ==========================================================
   CLOUD PLAN / LIMITS
   ========================================================== */
async function refreshCloudPlan() {
    try {
        const r = await fetch("/api/cloud/status", {cache:"no-store"});
        const d = await r.json();
        const plan = document.getElementById("cloudPlanName");
        const usage = document.getElementById("cloudPlanUsage");
        if (plan) plan.innerText = String(d.plan_code || "UNKNOWN").toUpperCase();
        const cu = Number((d.usage||{}).cameras||0), du = Number((d.usage||{}).drones||0);
        const cl = (d.limits||{}).cameras, dl = (d.limits||{}).drones;
        if (usage) usage.innerText = `CAMERAS ${cu}/${cl == null ? "∞" : cl}  •  DRONES ${du}/${dl == null ? "∞" : dl}`;
        const faceBtn=document.getElementById("openFaceEnroll"), vehicleBtn=document.getElementById("openVehicleEnroll");
        if(faceBtn){faceBtn.disabled=!d.face_ai_allowed;faceBtn.title=d.face_ai_allowed?"":"Face AI is not included in this plan.";}
        if(vehicleBtn){vehicleBtn.disabled=!d.lpr_allowed;vehicleBtn.title=d.lpr_allowed?"":"LPR is not included in this plan.";}
    } catch(e) {}
}
refreshCloudPlan();
setInterval(refreshCloudPlan, 10000);

/* ==========================================================
   CAMERA AI ON / OFF
   ========================================================== */

const cameraToggle = document.getElementById("cameraToggle");
let cameraEnabled = true;
let cameraBusy = false;

function paintCameraButton(enabled, mqttOk=true) {
    if (!cameraToggle) return;
    cameraEnabled = !!enabled;
    if (!mqttOk) {
        cameraToggle.innerText = "CAMERA AI • MQTT OFFLINE";
        cameraToggle.style.borderColor = "#8c3030";
        cameraToggle.style.color = "#ff6262";
        cameraToggle.style.boxShadow = "none";
        return;
    }
    if (cameraEnabled) {
        cameraToggle.innerText = "CAMERA AI • ON — CLICK TO STOP";
        cameraToggle.style.borderColor = "#19d978";
        cameraToggle.style.color = "#35f59a";
        cameraToggle.style.boxShadow = "0 0 16px rgba(25,217,120,.18)";
    } else {
        cameraToggle.innerText = "CAMERA AI • OFF — CLICK TO START";
        cameraToggle.style.borderColor = "#9a6200";
        cameraToggle.style.color = "#ffb23c";
        cameraToggle.style.boxShadow = "none";
    }
}

async function refreshCameraStatus() {
    try {
        const response = await fetch("/api/camera/status", {cache: "no-store"});
        const data = await response.json();
        paintCameraButton(data.enabled, data.mqtt);
    } catch (error) {
        paintCameraButton(false, false);
    }
}

if (cameraToggle) {
    cameraToggle.addEventListener("click", async () => {
        if (cameraBusy) return;
        const nextState = !cameraEnabled;
        cameraBusy = true;
        cameraToggle.disabled = true;
        cameraToggle.innerText = nextState ? "STARTING CAMERA AI..." : "STOPPING CAMERA AI...";
        try {
            const response = await fetch("/api/camera/toggle", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({enabled: nextState}),
            });
            const result = await response.json();
            if (!response.ok || !result.ok) throw new Error(result.error || "Unable to change camera state.");
            paintCameraButton(result.enabled, true);
        } catch (error) {
            alert(error.message || "Unable to change camera state.");
            await refreshCameraStatus();
        } finally {
            cameraBusy = false;
            cameraToggle.disabled = false;
        }
    });
}

refreshCameraStatus();
setInterval(refreshCameraStatus, 3000);


/* ==========================================================
   OBJECT AI ON / OFF + LIVE LABEL LIST
   ========================================================== */
const objectAiToggle = document.getElementById("objectAiToggle");
const objectAiList = document.getElementById("objectAiList");
const objectAiCount = document.getElementById("objectAiCount");
let objectAiEnabled = true;

function paintObjectAi(data) {
    objectAiEnabled = !!data.enabled;
    if (objectAiToggle) {
        objectAiToggle.innerText = objectAiEnabled ? "OBJECT AI • ON — CLICK TO STOP" : "OBJECT AI • OFF — CLICK TO START";
        objectAiToggle.style.borderColor = objectAiEnabled ? "#19d978" : "#9a6200";
        objectAiToggle.style.color = objectAiEnabled ? "#35f59a" : "#ffb23c";
    }
    const objects = Array.isArray(data.objects) ? data.objects : [];
    if (objectAiCount) objectAiCount.innerText = objects.length;
    if (objectAiList) {
        objectAiList.innerHTML = objects.length ? objects.slice(0, 8).map(o => {
            const c = (o.confidence === null || o.confidence === undefined) ? "" : ` — ${o.confidence}%`;
            return `<div><b>${o.label}</b>${c} <span style="color:#617f8f">[${o.source}]</span></div>`;
        }).join("") : (objectAiEnabled ? "WAITING FOR OBJECTS..." : "OBJECT AI DISABLED");
    }
}
async function refreshObjectAi() {
    try { const r=await fetch("/api/object_ai/status", {cache:"no-store"}); paintObjectAi(await r.json()); } catch(e) {}
}
if (objectAiToggle) objectAiToggle.addEventListener("click", async () => {
    objectAiToggle.disabled = true;
    try {
        const r=await fetch("/api/object_ai/toggle", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({enabled:!objectAiEnabled})});
        paintObjectAi(await r.json());
        await refreshObjectAi();
    } finally { objectAiToggle.disabled=false; }
});
refreshObjectAi();
setInterval(refreshObjectAi, 1500);

/* ==========================================================
   DRONE AI ON / OFF
   ========================================================== */

const droneToggle = document.getElementById("droneToggle");
let droneEnabled = false;
let droneVideoOnline = false;
let droneBusy = false;

function paintDroneButton(enabled, mqttOk=true) {
    if (!droneToggle) return;
    droneEnabled = !!enabled;

    if (!mqttOk) {
        droneToggle.innerText = "DRONE AI • MQTT OFFLINE";
        droneToggle.style.borderColor = "#8c3030";
        droneToggle.style.color = "#ff6262";
        droneToggle.style.boxShadow = "none";
        return;
    }

    if (droneEnabled) {
        droneToggle.innerText = "DRONE AI • ON — CLICK TO STOP";
        droneToggle.style.borderColor = "#19d978";
        droneToggle.style.color = "#35f59a";
        droneToggle.style.boxShadow = "0 0 16px rgba(25,217,120,.18)";
    } else {
        droneToggle.innerText = "DRONE AI • OFF — CLICK TO START";
        droneToggle.style.borderColor = "#9a6200";
        droneToggle.style.color = "#ffb23c";
        droneToggle.style.boxShadow = "none";
    }
}

async function refreshDroneStatus() {
    try {
        const response = await fetch("/api/drone/status", {cache: "no-store"});
        const data = await response.json();
        droneVideoOnline = !!data.video;
        paintDroneButton(data.enabled, data.mqtt);
    } catch (error) {
        paintDroneButton(false, false);
    }
}

if (droneToggle) {
    droneToggle.addEventListener("click", async () => {
        if (droneBusy) return;
        const nextState = !droneEnabled;

        if (nextState) {
            const confirmed = confirm(
                "Start DRONE AI?\n\nMake sure DJI Fly is already livestreaming to the PC first."
            );
            if (!confirmed) return;
        }

        droneBusy = true;
        droneToggle.disabled = true;
        droneToggle.innerText = nextState ? "STARTING DRONE AI..." : "STOPPING DRONE AI...";

        try {
            const response = await fetch("/api/drone/toggle", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({enabled: nextState}),
            });
            const result = await response.json();
            if (!response.ok || !result.ok) {
                throw new Error(result.error || "Unable to change drone state.");
            }
            paintDroneButton(result.enabled, true);
        } catch (error) {
            alert(error.message || "Unable to change drone state.");
            await refreshDroneStatus();
        } finally {
            droneBusy = false;
            droneToggle.disabled = false;
        }
    });
}

refreshDroneStatus();
setInterval(refreshDroneStatus, 3000);


/* DRONE TRACKING ASSIST */
const droneTrackingToggle = document.getElementById("droneTrackingToggle");
const droneTrackState = document.getElementById("droneTrackState");
const droneTrackLabel = document.getElementById("droneTrackLabel");
const droneTrackDirection = document.getElementById("droneTrackDirection");
let droneTrackingEnabled = false;
let latestDroneTrackingStatus = {
    enabled: false,
    active: false,
    known: false,
    label: "",
    direction: "WAITING"
};

function paintDroneTracking(d) {
    latestDroneTrackingStatus = d || latestDroneTrackingStatus;
    droneTrackingEnabled = !!d.enabled;
    if (droneTrackingToggle) {
        droneTrackingToggle.innerText = droneTrackingEnabled ? "DRONE TRACKING ASSIST • ON — CLICK TO STOP" : "DRONE TRACKING ASSIST • OFF — CLICK TO START";
        droneTrackingToggle.style.borderColor = droneTrackingEnabled ? "#18d67b" : "#385e74";
        droneTrackingToggle.style.color = droneTrackingEnabled ? "#35f59a" : "#7edcff";
    }
    if (!droneTrackingEnabled) {
        droneTrackState.innerText = "OFF"; droneTrackLabel.innerText = "NO TARGET"; droneTrackDirection.innerText = "WAITING"; droneTrackDirection.style.color = "#34d9ff"; return;
    }
    droneTrackState.innerText = d.active ? "LOCKED" : "SEARCHING";
    droneTrackLabel.innerText = d.active ? (d.label || "TARGET") : "SEARCHING FOR PERSON / VEHICLE";
    droneTrackDirection.innerText = d.active ? (d.direction || "CENTERED") : "WAITING";
    droneTrackDirection.style.color = d.active ? (d.known ? "#31ed88" : "#ff9e32") : "#34d9ff";
}
async function refreshDroneTracking() {
    try { const r = await fetch("/api/drone/tracking/status", {cache:"no-store"}); paintDroneTracking(await r.json()); } catch (e) {}
}
if (droneTrackingToggle) {
    droneTrackingToggle.addEventListener("click", async () => {
        const next = !droneTrackingEnabled;
        if (next && !droneEnabled) { alert("Start DRONE AI first, then enable Tracking Assist."); return; }
        const r = await fetch("/api/drone/tracking/toggle", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({enabled:next})});
        const d = await r.json();
        if (!r.ok || !d.ok) { alert(d.error || "Unable to change tracking-assist state."); return; }
        refreshDroneTracking();
    });
}
setInterval(refreshDroneTracking, 1500);
refreshDroneTracking();


/* ==========================================================
   EVENT HISTORY BUTTON
   ========================================================== */

const eventHistoryOverlay = document.getElementById("eventHistoryOverlay");

function openEventHistory() {
    if (eventHistoryOverlay) eventHistoryOverlay.classList.add("open");
}

function closeEventHistory() {
    if (eventHistoryOverlay) eventHistoryOverlay.classList.remove("open");
}

document.getElementById("goHistory").addEventListener("click", openEventHistory);

document.getElementById("viewAllHistory").addEventListener("click", openEventHistory);

document.getElementById("closeEventHistory").addEventListener("click", closeEventHistory);

eventHistoryOverlay.addEventListener("click", event => {
    if (event.target === eventHistoryOverlay) closeEventHistory();
});

// Delete buttons ask on the page itself (click again to confirm): the browser's own confirm box
// can be switched off ("don't let this page create more dialogs"), which made deleting do nothing.
function armedForDelete(button, question) {
    if (button.dataset.armed === "1") return true;
    button.dataset.armed = "1";
    button.dataset.label = button.innerText;
    button.innerText = question;
    button.classList.add("confirm-armed");
    clearTimeout(button._disarm);
    button._disarm = setTimeout(() => {
        button.dataset.armed = "";
        button.innerText = button.dataset.label;
        button.classList.remove("confirm-armed");
    }, 4000);
    return false;
}

document.getElementById("clearAllEvents").addEventListener("click", async () => {
    const button = document.getElementById("clearAllEvents");
    if (!armedForDelete(button, "CLICK AGAIN TO CLEAR ALL EVENTS")) return;
    clearTimeout(button._disarm);
    const oldText = button.dataset.label;
    button.disabled = true;
    button.innerText = "CLEARING...";

    try {
        const response = await fetch("/api/events", {method: "DELETE"});
        const result = await response.json();
        if (!result.ok) throw new Error(result.error || "Unable to clear event history.");
        window.location.reload();
    } catch (error) {
        alert(error.message || "Unable to clear event history.");
        button.disabled = false;
        button.innerText = oldText;
    }
});


/* ==========================================================
   DELETE SECURITY EVENT
   ========================================================== */

document.addEventListener("click", async event => {
    const button = event.target.closest(".delete-event-button");
    if (!button) return;

    const eventIndex = Number(button.dataset.eventIndex);
    if (!armedForDelete(button, "CLICK AGAIN TO DELETE")) return;
    clearTimeout(button._disarm);
    const oldText = button.dataset.label;
    button.disabled = true;
    button.innerText = "DELETING...";

    try {
        const response = await fetch("/api/events/" + eventIndex, {
            method: "DELETE",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({key: button.dataset.eventKey || ""}),
        });
        const result = await response.json();
        if (!result.ok) throw new Error(result.error || "Unable to delete event.");

        const card = button.closest(".event");
        if (card) {
            card.style.opacity = "0";
            card.style.transform = "scale(.94)";
            card.style.transition = ".25s ease";
        }
        setTimeout(() => window.location.reload(), 260);
    } catch (error) {
        alert(error.message || "Unable to delete event.");
        button.disabled = false;
        button.innerText = oldText;
    }
});


/* ==========================================================
   BIOMETRIC SCANNER AUDIO
   ========================================================== */

let biometricAudio = null;
let biometricBeepTimer = null;
let biometricSoundRunning = false;
let biometricLastStage = "";
let biometricFinishedState = "";

function getBiometricAudio() {
    if (!biometricAudio) {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return null;
        biometricAudio = new AudioContext();
    }
    if (biometricAudio.state === "suspended") biometricAudio.resume();
    return biometricAudio;
}

function scannerBeep(frequency=900, duration=0.055, volume=0.035) {
    const audio = getBiometricAudio();
    if (!audio) return;
    const oscillator = audio.createOscillator();
    const gain = audio.createGain();
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(frequency, audio.currentTime);
    gain.gain.setValueAtTime(volume, audio.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + duration);
    oscillator.connect(gain);
    gain.connect(audio.destination);
    oscillator.start();
    oscillator.stop(audio.currentTime + duration);
}

function biometricPulse() {
    scannerBeep(Math.random() > .5 ? 880 : 1120, .05, .032);
}

function startBiometricSound() {
    stopBiometricSound();
    biometricSoundRunning = true;
    biometricLastStage = "";
    biometricFinishedState = "";
    scannerBeep(620, .07, .04);
    setTimeout(() => scannerBeep(930, .06, .035), 90);
    biometricBeepTimer = setInterval(biometricPulse, 520);
}

function changeBiometricSpeed(milliseconds) {
    if (!biometricSoundRunning) return;
    clearInterval(biometricBeepTimer);
    biometricBeepTimer = setInterval(biometricPulse, milliseconds);
}

function stopBiometricSound() {
    biometricSoundRunning = false;
    if (biometricBeepTimer) clearInterval(biometricBeepTimer);
    biometricBeepTimer = null;
}

function biometricSuccessSound() {
    stopBiometricSound();
    scannerBeep(750, .08, .04);
    setTimeout(() => scannerBeep(1050, .08, .04), 100);
    setTimeout(() => scannerBeep(1450, .16, .045), 210);
}

function biometricFailureSound() {
    stopBiometricSound();
    scannerBeep(520, .13, .045);
    setTimeout(() => scannerBeep(360, .20, .045), 150);
}




/* Stream the enrollment preview only while its window is open, so the dashboard
   doesn't decode the camera in the background. */
(function () {
    const overlay = document.getElementById("faceEnrollOverlay");
    const feed = document.getElementById("enrollCameraFeed");
    if (!overlay || !feed) return;
    const sync = () => {
        if (overlay.classList.contains("open")) {
            if (feed.dataset.on !== "1") { feed.src = feed.dataset.src || "/video_feed"; feed.dataset.on = "1"; }
        } else if (feed.dataset.on === "1") {
            feed.src = "data:,";  // aborts the open MJPEG connection
            feed.dataset.on = "0";
        }
    };
    new MutationObserver(sync).observe(overlay, {attributes: true, attributeFilter: ["class"]});
    sync();
})();

/* Enrollment source preview */
const faceEnrollSource = document.getElementById("faceEnrollSource");
if (faceEnrollSource) {
    faceEnrollSource.addEventListener("change", () => {
        const feed = document.getElementById("enrollCameraFeed");
        if (feed) {
            feed.dataset.src = faceEnrollSource.value === "drone" ? "/drone_video_feed" : "/video_feed";
            if (feed.dataset.on === "1") feed.src = feed.dataset.src;
        }
        const msg = document.getElementById("enrollMessage");
        if (msg) msg.innerText = faceEnrollSource.value === "drone"
            ? "DRONE selected — turn Drone AI ON and position one face clearly in the drone view."
            : "MAIN CAMERA selected — position the person's face inside the scanner.";
    });
}

/* ==========================================================
   START FACE BIOMETRIC ENROLLMENT
   ========================================================== */

document.getElementById(
    "startFaceEnrollment"
).addEventListener(
    "click",
    async () => {

        const name =
            document.getElementById(
                "faceName"
            ).value.trim();
        const source = document.getElementById("faceEnrollSource").value;


        if (!name) {

            document.getElementById(
                "enrollMessage"
            ).innerText =
                "Enter the person's name first.";

            return;
        }


        getBiometricAudio();
        startBiometricSound();


        const button =
            document.getElementById(
                "startFaceEnrollment"
            );


        button.disabled = true;

        button.innerText =
            "INITIALIZING BIOMETRIC SCAN";


        try {

            const response =
                await fetch(
                    "/api/enroll/face",
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body:
                            JSON.stringify({
                                name: name,
                                source: source
                            })
                    }
                );


            const result =
                await response.json();


            if (!result.ok) {

                document.getElementById(
                    "enrollMessage"
                ).innerText =
                    result.error
                    ||
                    "Could not start enrollment.";

                button.disabled = false;

                button.innerText =
                    "START BIOMETRIC SCAN";
                biometricFailureSound();
            }

        }

        catch (error) {

            document.getElementById(
                "enrollMessage"
            ).innerText =
                "Enrollment request failed.";

            button.disabled = false;

            button.innerText =
                "START BIOMETRIC SCAN";
            biometricFailureSound();
        }
    }
);


/* ==========================================================
   CANCEL FACE ENROLLMENT
   ========================================================== */

document.getElementById(
    "cancelFaceEnrollment"
).addEventListener(
    "click",
    async () => {

        await fetch(
            "/api/enroll/cancel",
            {
                method: "POST"
            }
        );

        document.getElementById(
            "enrollMessage"
        ).innerText =
            "Cancelling biometric scan...";

        stopBiometricSound();
    }
);


/* ==========================================================
   FACE ENROLLMENT STATUS
   ========================================================== */

async function refreshEnrollment() {

    try {

        const response =
            await fetch(
                "/api/enroll/status"
            );

        const d =
            await response.json();

        if (d.running && d.stage !== biometricLastStage) {
            biometricLastStage = d.stage;
            if (d.stage === "BIOMETRIC CAPTURE") {
                changeBiometricSpeed(210);
                scannerBeep(1350, .07, .04);
            } else if (d.stage === "REGISTERING") {
                changeBiometricSpeed(280);
                scannerBeep(1050, .08, .04);
            } else if (d.stage === "SAMPLE ACCEPTED") {
                changeBiometricSpeed(500);
                scannerBeep(1550, .09, .045);
            } else {
                changeBiometricSpeed(520);
            }
        }

        if (d.success && biometricFinishedState !== "success") {
            biometricFinishedState = "success";
            biometricSuccessSound();
        } else if (!d.running && d.error && biometricFinishedState !== "failure") {
            biometricFinishedState = "failure";
            biometricFailureSound();
        }


        document.getElementById(
            "enrollStage"
        ).innerText =
            d.stage;


        document.getElementById(
            "enrollPercent"
        ).innerText =
            d.progress
            + "%";


        document.getElementById(
            "enrollProgress"
        ).style.width =
            d.progress
            + "%";


        document.getElementById(
            "enrollScannerText"
        ).innerText =
            d.stage;


        document.getElementById(
            "enrollMessage"
        ).innerText =
            d.error
            ||
            d.message;


        for (
            let i = 1;
            i <= 5;
            i++
        ) {

            const dot =
                document.getElementById(
                    "sample" + i
                );


            if (
                i <=
                (
                    d.success
                    ? 5
                    : Math.max(
                        0,
                        d.sample - (
                            d.stage === "SAMPLE ACCEPTED"
                            ? 0
                            : 1
                        )
                    )
                )
            ) {

                dot.classList.add(
                    "complete"
                );

            }

            else {

                dot.classList.remove(
                    "complete"
                );
            }
        }


        const button =
            document.getElementById(
                "startFaceEnrollment"
            );


        if (d.running) {

            button.disabled = true;

            button.innerText =
                "BIOMETRIC SCAN IN PROGRESS";

        }

        else {

            button.disabled = false;

            button.innerText =
                d.success

                ? "ENROLL ANOTHER FACE"

                : "START BIOMETRIC SCAN";
        }


        const scanner =
            document.getElementById(
                "enrollScanner"
            );


        if (d.success) {

            scanner.style.borderColor =
                "#26e990";

            scanner.style.boxShadow =
                "inset 0 0 45px rgba(38,233,144,.12)";

        }

        else if (d.error) {

            scanner.style.borderColor =
                "#ff5062";

            scanner.style.boxShadow =
                "inset 0 0 45px rgba(255,80,98,.08)";

        }

        else {

            scanner.style.borderColor =
                "#087fb5";

            scanner.style.boxShadow =
                "none";
        }


    }

    catch (error) {

        console.log(
            "Enrollment status error:",
            error
        );
    }
}


setInterval(
    refreshEnrollment,
    400
);

refreshEnrollment();


/* ==========================================================
   ADD VEHICLE
   ========================================================== */

document.getElementById(
    "saveVehicle"
).addEventListener(
    "click",
    async () => {

        const vehicle =
            document.getElementById(
                "newVehicleName"
            ).value.trim();

        const plate =
            document.getElementById(
                "newVehiclePlate"
            ).value.trim();
        const source = document.getElementById("vehicleEnrollSource").value;


        const output =
            document.getElementById(
                "vehicleSaveMessage"
            );


        output.innerText =
            "Registering vehicle...";


        try {

            const response =
                await fetch(
                    "/api/add_vehicle",
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body:
                            JSON.stringify({
                                vehicle: vehicle,
                                plate: plate,
                                source: source
                            })
                    }
                );


            const result =
                await response.json();


            if (result.ok) {

                output.innerText =
                    "✓ VEHICLE REGISTERED — "
                    + result.vehicle
                    + " • "
                    + result.plate;

            }

            else {

                output.innerText =
                    result.error;
            }

        }

        catch (error) {

            output.innerText =
                "Unable to register vehicle.";
        }
    }
);


/* ==========================================================
   FACE LIBRARY
   ========================================================== */

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
}

document.getElementById(
    "openFaceLibrary"
).addEventListener(
    "click",
    async () => {

        faceLibraryOverlay
            .classList
            .add("open");


        const container =
            document.getElementById(
                "faceLibraryContent"
            );


        container.innerHTML =
            '<div class="waiting">Loading face library...</div>';


        try {

            const response =
                await fetch(
                    "/api/face_library"
                );

            const result =
                await response.json();


            if (
                !result.ok
                ||
                !result.faces.length
            ) {

                container.innerHTML =
                    '<div class="waiting">'
                    +
                    escapeHtml(
                        result.error
                        ||
                        "No enrolled faces found."
                    )
                    +
                    '</div>';

                return;
            }


            container.innerHTML =
                result.faces.map(
                    name => `

                        <div class="library-item">

                            <div class="library-type">
                                ENROLLED IDENTITY
                            </div>

                            <div class="library-name">
                                ${escapeHtml(name)}
                            </div>

                            <div class="library-sub">
                                FACE RECOGNITION
                            </div>

                        </div>

                    `
                ).join("");

        }

        catch (error) {

            container.innerHTML =
                '<div class="waiting">Unable to read face library.</div>';
        }
    }
);


/* ==========================================================
   KNOWN VEHICLES
   ========================================================== */

document.getElementById(
    "openVehicleLibrary"
).addEventListener(
    "click",
    async () => {

        vehicleLibraryOverlay
            .classList
            .add("open");


        const container =
            document.getElementById(
                "vehicleLibraryContent"
            );


        container.innerHTML =
            '<div class="waiting">Loading known vehicles...</div>';


        try {

            const response =
                await fetch(
                    "/api/known_vehicles"
                );

            const vehicles =
                await response.json();

            const entries =
                Object.entries(
                    vehicles
                );


            if (!entries.length) {

                container.innerHTML =
                    '<div class="waiting">No registered vehicles.</div>';

                return;
            }


            container.innerHTML =
                entries.map(
                    ([plate, name]) => `

                        <div class="library-item">

                            <div class="library-type">
                                AUTHORIZED VEHICLE
                            </div>

                            <div class="library-name">
                                ${escapeHtml(name)}
                            </div>

                            <div class="library-sub">
                                PLATE • ${escapeHtml(plate)}
                            </div>

                        </div>

                    `
                ).join("");

        }

        catch (error) {

            container.innerHTML =
                '<div class="waiting">Unable to read known vehicles.</div>';
        }
    }
);



/* DRONE FEED STATUS
   Uses already-cached Drone AI + tracking state.
   No extra HTTP requests are generated here. */
function refreshDroneFeedStatus() {
    // The drone video itself is played (and reconnected) by the shared live player.
    const stateEl = document.getElementById("droneFeedState");
    if (stateEl) {
        stateEl.innerText = droneVideoOnline ? "● VIDEO LIVE" : (droneEnabled ? "WAITING FOR VIDEO" : "NO VIDEO");
        stateEl.style.color = droneVideoOnline ? "#2fee91" : "#ffae2b";
    }

    const ts = latestDroneTrackingStatus || {};
    const out = document.getElementById("droneTrackingReadout");
    if (out) {
        if (!ts.enabled) out.innerText = "TRACKING ASSIST • OFF";
        else if (!ts.active) out.innerText = "TRACKING ASSIST • SEARCHING";
        else out.innerText =
            "TRACKING • "
            + (ts.label || "TARGET")
            + " • "
            + (ts.direction || "CENTERED");
    }
}
setInterval(refreshDroneFeedStatus, 1000);
refreshDroneFeedStatus();

/* Old links like /#history now go to the Events / People / Vehicles pages under Settings. */
function openPanelFromHash() {
    const h = location.hash, to = {"#history": "/settings/events", "#face-library": "/settings/people", "#vehicle-library": "/settings/vehicles"}[h];
    if (to && location.pathname === "/") location.replace(to);
}
window.addEventListener("hashchange", openPanelFromHash);
openPanelFromHash();
</script>


</body>

</html>
"""
