"""Shared look of the HUD pages."""
HUD_CSS = r"""
*{box-sizing:border-box}
html,body{margin:0;min-height:100%}
body{background:#02070c;color:#d9efff;font-family:Arial,Helvetica,sans-serif;overflow-x:hidden}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
  background-image:linear-gradient(rgba(20,135,180,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(20,135,180,.025) 1px,transparent 1px);
  background-size:40px 40px}
a{color:#5bd9ff}

/* top bar */
.hud-top{position:sticky;top:0;z-index:20;display:flex;align-items:stretch;min-height:64px;background:#03101a;
  border-bottom:1px solid #0876ad;box-shadow:0 0 26px rgba(0,153,255,.10);overflow:hidden}
.hud-top::after{content:"";position:absolute;bottom:0;left:-40%;width:40%;height:1px;
  background:linear-gradient(90deg,transparent,#36cfff,transparent);animation:topSweep 4s linear infinite}
@keyframes topSweep{to{left:100%}}
.hud-brand{display:flex;align-items:center;gap:11px;padding:0 18px;border-right:1px solid #12405a;text-decoration:none;flex:none}
.brand-shield{width:40px;height:45px;display:flex;align-items:center;justify-content:center;
  clip-path:polygon(50% 0,92% 15%,84% 74%,50% 100%,16% 74%,8% 15%);background:rgba(18,151,215,.20);
  color:#45d0ff;font-size:18px;border:1px solid #31c6ff}
.brand-name{color:#5bd9ff;font-size:17px;font-weight:bold;letter-spacing:2px}
.brand-sub{margin-top:2px;color:#4a91b2;font-size:8px;letter-spacing:2px}
.hud-nav{display:flex;flex:1;overflow-x:auto;scrollbar-width:none}
.hud-nav::-webkit-scrollbar{display:none}
.hud-nav a{position:relative;display:flex;align-items:center;gap:8px;padding:0 16px;color:#6d8b9d;text-decoration:none;
  font-size:10px;letter-spacing:1.5px;text-transform:uppercase;border-right:1px solid #123447;white-space:nowrap;transition:.2s}
.hud-nav a .ico{color:#2f7fa3;font-size:13px}
.hud-nav a:hover{color:#bfefff;background:rgba(14,88,128,.12)}
.hud-nav a.active{color:#5bd9ff;background:rgba(18,151,215,.10)}
.hud-nav a.active .ico{color:#45d0ff}
.hud-nav a.active::after{content:"";position:absolute;left:0;right:0;bottom:0;height:2px;background:#36cfff;box-shadow:0 0 10px #36cfff}
.hud-clock{display:flex;flex-direction:column;justify-content:center;align-items:flex-end;padding:0 18px;border-left:1px solid #12405a;min-width:150px;flex:none}
.hud-clock b{color:#e9f8ff;font-size:16px;letter-spacing:1px}
.hud-clock span{margin-top:3px;color:#24ed87;font-size:9px;letter-spacing:1.5px;display:flex;align-items:center;gap:6px}

/* layout */
.hud-main{position:relative;z-index:1;max-width:1500px;margin:0 auto;padding:22px 24px 40px}
.hud-main.narrow{max-width:920px}
.page-head{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;margin-bottom:18px;flex-wrap:wrap}
.page-kicker{color:#4a91b2;font-size:10px;letter-spacing:3px;text-transform:uppercase}
.page-title{margin:6px 0 0;color:#5bd9ff;font-size:22px;letter-spacing:2px;text-transform:uppercase;font-weight:bold;text-shadow:0 0 18px rgba(54,207,255,.25)}
.page-sub{color:#6d8b9d;font-size:12px;margin-top:6px;letter-spacing:.5px;line-height:1.5}
.actions{display:flex;gap:8px;flex-wrap:wrap}
.grid-2{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(320px,.8fr);gap:16px;align-items:start}
.stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:16px}

/* panels */
.panel{position:relative;overflow:hidden;background:#04111b;border:1px solid #0a5480;border-radius:6px;box-shadow:0 0 20px rgba(0,126,188,.08);margin-bottom:16px}
.panel::before{content:"";position:absolute;top:0;left:0;width:130px;height:1px;background:linear-gradient(90deg,#36cfff,transparent)}
.panel-head{min-height:43px;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:0 14px;border-bottom:1px solid #123447}
.panel-title{color:#a8c7d7;font-size:11px;letter-spacing:1.5px;text-transform:uppercase}
.panel-body{padding:16px}
.live{color:#2aea88;font-size:10px;letter-spacing:1px}
.stat{position:relative;overflow:hidden;background:#04111b;border:1px solid #0a5480;border-radius:6px;padding:14px 16px}
.stat::after{content:"";position:absolute;bottom:0;left:-100%;width:100%;height:1px;background:linear-gradient(90deg,transparent,#36cfff,transparent);animation:topSweep 4s linear infinite}
.stat-label{color:#6d8b9d;font-size:10px;letter-spacing:1.5px;text-transform:uppercase}
.stat-value{margin-top:8px;font-size:15px;font-weight:bold;color:#e9f8ff;letter-spacing:.5px}

/* status dots */
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#4d6b7c;margin-right:8px;vertical-align:middle}
.dot.good{background:#26ee89;box-shadow:0 0 10px #26ee89;animation:pulseDot 1.4s infinite}
.dot.warn{background:#ffb23c;box-shadow:0 0 10px #ffb23c;animation:pulseDot 1.4s infinite}
.dot.bad{background:#ff5d6c;box-shadow:0 0 10px #ff5d6c}
@keyframes pulseDot{50%{opacity:.35;transform:scale(.7)}}

/* video */
.camera-box{position:relative;background:#000;aspect-ratio:16/9}
.camera-box img{width:100%;height:100%;object-fit:contain;display:block}
.corner{position:absolute;width:34px;height:34px;pointer-events:none}
.corner.tl{top:14px;left:14px;border-top:2px solid #3dd8ff;border-left:2px solid #3dd8ff}
.corner.tr{top:14px;right:14px;border-top:2px solid #3dd8ff;border-right:2px solid #3dd8ff}
.corner.bl{bottom:14px;left:14px;border-bottom:2px solid #3dd8ff;border-left:2px solid #3dd8ff}
.corner.br{bottom:14px;right:14px;border-bottom:2px solid #3dd8ff;border-right:2px solid #3dd8ff}
.overlay-tag{position:absolute;left:56px;bottom:22px;background:rgba(3,16,26,.85);border:1px solid #155879;color:#9edfff;padding:7px 10px;border-radius:4px;font-size:10px;letter-spacing:1px;text-transform:uppercase}
.camera-footer{min-height:30px;display:flex;align-items:center;justify-content:space-between;padding:0 12px;color:#5d8499;font-size:9px;letter-spacing:1px}
.cam-name{color:#35caff}

/* rows, text */
.hud-row{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:12px 14px;background:#05131d;border:1px solid #153c56;border-radius:5px;margin-bottom:8px}
.hud-row:last-child{margin-bottom:0}
.hud-row b{color:#d9efff;font-size:13px;letter-spacing:.3px}
.muted{color:#6d8b9d;font-size:12px;line-height:1.5}
.state{color:#2aea88;font-size:11px;font-weight:bold;letter-spacing:1px}
code{color:#2eef88;background:#020a10;border:1px solid #123447;border-radius:3px;padding:2px 6px;font-size:12px;word-break:break-all}

/* buttons, inputs */
.hud-btn{min-height:36px;padding:0 16px;cursor:pointer;color:#66dfff;background:rgba(14,88,128,.12);border:1px solid #155879;border-radius:4px;
  font-size:10px;font-weight:bold;letter-spacing:1.5px;text-transform:uppercase;font-family:inherit;transition:.2s}
.hud-btn:hover{color:#fff;border-color:#35cbff;box-shadow:0 0 12px rgba(53,203,255,.16)}
.hud-btn.primary{color:#02131d;background:#25c7ff;border-color:#45d0ff;box-shadow:0 0 16px rgba(37,199,255,.25)}
.hud-btn.primary:hover{background:#5bd9ff;color:#02131d}
.hud-btn.danger{color:#ff7b86;border-color:#7a2935;background:rgba(125,12,28,.12)}
.hud-btn:disabled{opacity:.5;cursor:default;box-shadow:none}
label{display:block;margin:16px 0 7px;color:#a8c7d7;font-size:10px;letter-spacing:1.5px;text-transform:uppercase}
input[type=text],input[type=password],input[type=number],input:not([type]),select{width:100%;background:#020a10;color:#d9efff;border:1px solid #155879;
  border-radius:4px;padding:11px 12px;font-size:14px;font-family:inherit;outline:none;transition:.2s}
input:focus,select:focus{border-color:#36cfff;box-shadow:0 0 12px rgba(54,207,255,.18)}
input.toggle{appearance:none;-webkit-appearance:none;position:relative;flex:none;width:46px;height:24px;margin:0;border-radius:12px;
  background:#0a1c28;border:1px solid #155879;cursor:pointer;transition:.2s}
input.toggle::after{content:"";position:absolute;top:3px;left:3px;width:16px;height:16px;border-radius:50%;background:#4d6b7c;transition:.2s}
input.toggle:checked{background:rgba(37,199,255,.18);border-color:#36cfff;box-shadow:0 0 12px rgba(54,207,255,.2)}
input.toggle:checked::after{left:25px;background:#45d0ff;box-shadow:0 0 8px #45d0ff}
.hud-msg{margin-top:16px;padding:12px 14px;border-radius:5px;border:1px solid #155879;background:#05131d;font-size:13px;color:#9edfff}
.hud-msg:empty{display:none}
.hud-msg.ok{border-color:#1f7a50;color:#7dffc1;background:rgba(18,120,70,.12)}
.hud-msg.bad{border-color:#7a2935;color:#ff9ea8;background:rgba(125,12,28,.14)}
.notice{display:none}.notice.show{display:block}

/* events */
.event-row{display:grid;grid-template-columns:64px 1fr auto;gap:12px;align-items:center;padding:10px 0;border-bottom:1px solid #123447}
.event-row:last-child{border-bottom:0}
.thumb{width:64px;height:44px;border-radius:4px;border:1px solid #153c56;background:#05131d;object-fit:cover;display:block}
.event-type{color:#5bd9ff;font-size:11px;font-weight:bold;letter-spacing:1px;text-transform:uppercase}
.event-type.unknown{color:#ffb23c}

@media(max-width:1000px){.grid-2{grid-template-columns:1fr}.stat-grid{grid-template-columns:1fr 1fr}.hud-clock{display:none}}
@media(max-width:560px){.stat-grid{grid-template-columns:1fr}.brand-sub{display:none}.hud-main{padding:16px 12px 32px}}
"""
