"use client";
// Themed dialogs in the middle of the page, in place of the browser's alert / confirm / prompt.
//   await uiAlert("Saved.");
//   if(!await uiConfirm("Delete it?")) return;
//   const v = await uiPrompt("Name:", "Dock 1");   // null when cancelled
// Dialogs asked for while one is open wait their turn. Esc cancels, Enter confirms. Styles: .uiDlg* in globals.css.

type Kind = "alert" | "confirm" | "prompt";
export type DialogOptions = {title?: string; ok?: string; cancel?: string; danger?: boolean; value?: string};

const RISKY = /\b(delete|remove|revoke|block|switch off|turn off)\b/i;
let chain: Promise<unknown> = Promise.resolve();

function open(kind: Kind, message: string, opts: DialogOptions = {}): Promise<unknown> {
  const run = () => new Promise<unknown>(resolve => {
    const prev = document.activeElement as HTMLElement | null;
    const back = document.createElement("div"); back.className = "uiDlgBack";
    const box = document.createElement("div"); box.className = "uiDlg";
    box.setAttribute("role", kind === "alert" ? "alertdialog" : "dialog"); box.setAttribute("aria-modal", "true");
    const danger = opts.danger ?? (kind === "confirm" && RISKY.test(message));
    if (danger) box.classList.add("danger");
    const head = document.createElement("div"); head.className = "uiDlgHead";
    head.textContent = opts.title || (kind === "alert" ? "Notice" : kind === "prompt" ? "Enter a value" : danger ? "Please confirm" : "Confirm");
    const body = document.createElement("div"); body.className = "uiDlgBody"; body.textContent = message;
    let input: HTMLInputElement | null = null;
    if (kind === "prompt") { input = document.createElement("input"); input.value = opts.value ?? ""; body.appendChild(input); }
    const btns = document.createElement("div"); btns.className = "uiDlgBtns";
    const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "ghost small"; cancel.textContent = opts.cancel || "Cancel";
    const ok = document.createElement("button"); ok.type = "button"; ok.className = (danger ? "ghost danger" : "btn") + " small"; ok.textContent = opts.ok || "OK";
    if (kind !== "alert") btns.appendChild(cancel);
    btns.appendChild(ok);
    box.append(head, body, btns); back.appendChild(box); document.body.appendChild(back);
    const done = (v: unknown) => { document.removeEventListener("keydown", key, true); back.remove(); prev?.focus?.(); resolve(v); };
    const yes = () => done(kind === "confirm" ? true : kind === "prompt" ? input!.value : undefined);
    const no = () => done(kind === "confirm" ? false : kind === "prompt" ? null : undefined);
    function key(e: KeyboardEvent){
      if (e.key === "Escape") { e.preventDefault(); no(); }
      else if (e.key === "Enter" && (kind !== "confirm" || document.activeElement !== cancel)) { e.preventDefault(); yes(); }
      else if (e.key === "Tab") {
        const f = [...box.querySelectorAll<HTMLElement>("input,button")], i = f.indexOf(document.activeElement as HTMLElement);
        e.preventDefault(); f[(i + (e.shiftKey ? -1 : 1) + f.length) % f.length].focus();
      }
    }
    document.addEventListener("keydown", key, true);
    ok.onclick = yes; cancel.onclick = no;
    back.addEventListener("mousedown", e => { if (e.target === back && kind !== "alert") no(); });
    (input || (danger && kind === "confirm" ? cancel : ok)).focus();
    input?.select();
  });
  const p = chain.then(run, run); chain = p.catch(() => undefined); return p;
}

export const uiAlert = (message: string, opts?: DialogOptions) => open("alert", message, opts) as Promise<void>;
export const uiConfirm = (message: string, opts?: DialogOptions) => open("confirm", message, opts) as Promise<boolean>;
export const uiPrompt = (message: string, value = "", opts?: DialogOptions) => open("prompt", message, {...opts, value}) as Promise<string | null>;
