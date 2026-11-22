"""Themed dialogs for every page: uiAlert / uiConfirm / uiPrompt replace the browser's alert, confirm and prompt.

They open in the middle of the page in the HUD look and return Promises:
    await uiAlert("Saved.")                       -> undefined
    if (!await uiConfirm("Delete it?")) return;   -> true / false
    const v = await uiPrompt("Name:", "Dock 1");  -> text, or null when cancelled
Dialogs asked for while one is open wait their turn. Esc cancels, Enter confirms.

TRIAL_HTML adds the free-trial counter (top right) and, in the last day, a themed reminder to choose a plan.
"""
DIALOG_HTML = r"""
<style id="uiDialogCss">
.ui-dlg-back{position:fixed;inset:0;z-index:100000;display:flex;align-items:center;justify-content:center;padding:16px;
  background:rgba(1,6,10,.72);backdrop-filter:blur(3px);animation:uiDlgFade .12s ease-out}
@keyframes uiDlgFade{from{opacity:0}to{opacity:1}}
.ui-dlg{position:relative;width:min(480px,100%);max-height:calc(100vh - 32px);overflow:auto;background:#03101a;border:1px solid #0876ad;
  border-radius:6px;box-shadow:0 0 40px rgba(0,153,255,.22),0 20px 60px rgba(0,0,0,.6);color:#d9efff;font-family:Arial,Helvetica,sans-serif;
  animation:uiDlgPop .14s ease-out}
@keyframes uiDlgPop{from{transform:scale(.96);opacity:0}to{transform:none;opacity:1}}
.ui-dlg::before{content:"";position:absolute;left:0;right:0;top:0;height:2px;background:linear-gradient(90deg,transparent,#36cfff,transparent)}
.ui-dlg.danger{border-color:#a3303f;box-shadow:0 0 40px rgba(255,60,80,.18),0 20px 60px rgba(0,0,0,.6)}
.ui-dlg.danger::before{background:linear-gradient(90deg,transparent,#ff5d6c,transparent)}
.ui-dlg-head{padding:14px 18px 0;color:#5bd9ff;font:bold 11px Arial,sans-serif;letter-spacing:2px;text-transform:uppercase}
.ui-dlg.danger .ui-dlg-head{color:#ff9ea8}
.ui-dlg-body{padding:10px 18px 4px;font-size:14px;line-height:1.5;white-space:pre-line;word-wrap:break-word}
.ui-dlg-body input{display:block;width:100%;box-sizing:border-box;margin-top:10px;padding:10px 12px;background:#020a10;color:#e9f8ff;
  border:1px solid #155879;border-radius:4px;font:14px Arial,sans-serif;outline:none}
.ui-dlg-body input:focus{border-color:#36cfff;box-shadow:0 0 0 2px rgba(54,207,255,.2)}
.ui-dlg-btns{display:flex;justify-content:flex-end;gap:8px;padding:14px 18px 16px;flex-wrap:wrap}
.ui-dlg-btns button{min-width:92px;padding:10px 16px;border-radius:4px;border:1px solid #155879;background:#05131d;color:#9edfff;
  font:bold 11px Arial,sans-serif;letter-spacing:1.5px;text-transform:uppercase;cursor:pointer}
.ui-dlg-btns button:hover{border-color:#36cfff;color:#fff}
.ui-dlg-btns button.ok{background:#25c7ff;border-color:#45d0ff;color:#02131d;box-shadow:0 0 16px rgba(37,199,255,.25)}
.ui-dlg-btns button.ok:hover{background:#5bd9ff}
.ui-dlg.danger .ui-dlg-btns button.ok{background:#c2283c;border-color:#ff5d6c;color:#fff;box-shadow:0 0 16px rgba(255,60,80,.25)}
.ui-dlg-btns button:focus-visible{outline:2px solid #5bd9ff;outline-offset:2px}
</style>
<script id="uiDialogJs">
(function(){
  if(window.uiConfirm)return;
  let chain=Promise.resolve();
  // Messages that warn about flying, deleting or switching things off are shown in red.
  const RISKY=/\b(delete|remove|unpair|emergency|real flight|take off|takes off|without asking|by itself|anyway|revoke|switch off|turn off|log out)\b/i;
  function open(kind,message,opts){
    opts=opts||{};
    const run=()=>new Promise(resolve=>{
      const prev=document.activeElement;
      const back=document.createElement('div');back.className='ui-dlg-back';
      const box=document.createElement('div');box.className='ui-dlg';box.setAttribute('role',kind==='alert'?'alertdialog':'dialog');box.setAttribute('aria-modal','true');
      const danger=opts.danger!=null?opts.danger:(kind==='confirm'&&RISKY.test(String(message)));
      if(danger)box.classList.add('danger');
      const head=document.createElement('div');head.className='ui-dlg-head';
      head.textContent=opts.title||(kind==='alert'?'Notice':kind==='prompt'?'Enter a value':danger?'Please confirm':'Confirm');
      const body=document.createElement('div');body.className='ui-dlg-body';body.textContent=String(message==null?'':message);
      let input=null;
      if(kind==='prompt'){input=document.createElement('input');input.value=opts.value==null?'':String(opts.value);body.appendChild(input)}
      const btns=document.createElement('div');btns.className='ui-dlg-btns';
      const cancel=document.createElement('button');cancel.type='button';cancel.textContent=opts.cancel||'Cancel';
      const ok=document.createElement('button');ok.type='button';ok.className='ok';ok.textContent=opts.ok||'OK';
      if(kind!=='alert')btns.appendChild(cancel);
      btns.appendChild(ok);
      box.append(head,body,btns);back.appendChild(box);document.body.appendChild(back);
      const done=v=>{document.removeEventListener('keydown',key,true);back.remove();try{prev&&prev.focus&&prev.focus()}catch(e){}resolve(v)};
      const yes=()=>done(kind==='confirm'?true:kind==='prompt'?input.value:undefined);
      const no=()=>done(kind==='confirm'?false:kind==='prompt'?null:undefined);
      function key(e){
        if(e.key==='Escape'){e.preventDefault();e.stopPropagation();no()}
        else if(e.key==='Enter'&&(kind!=='confirm'||document.activeElement!==cancel)){e.preventDefault();e.stopPropagation();yes()}
        else if(e.key==='Tab'){const f=[...box.querySelectorAll('input,button')];const i=f.indexOf(document.activeElement);
          e.preventDefault();f[(i+(e.shiftKey?-1:1)+f.length)%f.length].focus()}
        else e.stopPropagation();  // keep flying keys (W/A/S/D, Space) away from the page while a dialog is open
      }
      document.addEventListener('keydown',key,true);
      ok.onclick=yes;cancel.onclick=no;
      back.addEventListener('mousedown',e=>{if(e.target===back&&kind!=='alert')no()});
      (input||(danger&&kind==='confirm'?cancel:ok)).focus();
      if(input)input.select();
    });
    const p=chain.then(run,run);chain=p.catch(()=>{});return p;
  }
  window.uiAlert=(m,o)=>open('alert',m,o);
  window.uiConfirm=(m,o)=>open('confirm',m,o);
  window.uiPrompt=(m,v,o)=>open('prompt',m,Object.assign({value:v},o||{}));
})();
</script>
"""

TRIAL_HTML = r"""
<style>
#trialPill{position:fixed;top:72px;right:14px;z-index:9000;display:flex;align-items:center;gap:8px;padding:7px 12px;border-radius:4px;
  background:rgba(3,16,26,.94);border:1px solid #155879;color:#9edfff;font:bold 11px Arial,sans-serif;letter-spacing:1px;
  box-shadow:0 0 18px rgba(0,153,255,.15);text-decoration:none}
#trialPill b{color:#fff;font-variant-numeric:tabular-nums}
#trialPill.soon{border-color:#7a5a12;color:#ffcf7a;box-shadow:0 0 18px rgba(255,178,60,.2)}
#trialPill.over{border-color:#a3303f;color:#ff9ea8}
@media(max-width:700px){#trialPill{top:auto;bottom:46px;right:10px}}
</style>
<a id="trialPill" href="__CHOOSE_PLAN__" target="_blank" rel="noopener" title="Free trial: choose a plan in the portal before it ends">FREE TRIAL · <b id="trialLeft">…</b></a>
<script>
(function(){
  const END=__TRIAL_END_MS__,URL='__CHOOSE_PLAN__',pill=document.getElementById('trialPill'),out=document.getElementById('trialLeft');
  const pad=n=>String(n).padStart(2,'0');
  function tick(){
    const ms=END-Date.now();
    if(ms<=0){pill.className='over';out.textContent='ENDED · CHOOSE A PLAN';return}
    const s=Math.floor(ms/1000),d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);
    out.textContent=(d?d+'d ':'')+pad(h)+':'+pad(m)+':'+pad(s%60)+' LEFT';
    pill.className=ms<86400000?'soon':'';
  }
  tick();setInterval(tick,1000);
  // One day before the end: a reminder in the middle of the page, at most once a day on this browser.
  function remind(){
    const ms=END-Date.now();if(ms<=0||ms>86400000||!window.uiConfirm)return;
    const key='trialReminder:'+END,today=new Date().toDateString();
    try{if(localStorage.getItem(key)===today)return;localStorage.setItem(key,today)}catch(e){}
    const h=Math.max(1,Math.round(ms/3600000));
    uiConfirm('Your free trial ends in about '+h+' hour'+(h>1?'s':'')+' ('+new Date(END).toLocaleString()+').\n\n'
      +'When it ends, this PC switches off its features until your company chooses a plan. An admin can choose one in the portal now; nothing else changes.',
      {title:'Free trial ends tomorrow',ok:'Choose a plan',cancel:'Later',danger:false})
      .then(go=>{if(go)window.open(URL,'_blank','noopener')});
  }
  setTimeout(remind,1500);setInterval(remind,10*60*1000);
})();
</script>
"""


def trial_html(ends_at_ms, choose_plan_url):
    return (TRIAL_HTML.replace("__TRIAL_END_MS__", str(int(ends_at_ms)))
            .replace("__CHOOSE_PLAN__", choose_plan_url.replace('"', "%22").replace("'", "%27")))
