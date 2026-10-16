(function(){const a=document.createElement("link").relList;if(a&&a.supports&&a.supports("modulepreload"))return;for(const n of document.querySelectorAll('link[rel="modulepreload"]'))t(n);new MutationObserver(n=>{for(const o of n)if(o.type==="childList")for(const c of o.addedNodes)c.tagName==="LINK"&&c.rel==="modulepreload"&&t(c)}).observe(document,{childList:!0,subtree:!0});function s(n){const o={};return n.integrity&&(o.integrity=n.integrity),n.referrerPolicy&&(o.referrerPolicy=n.referrerPolicy),n.crossOrigin==="use-credentials"?o.credentials="include":n.crossOrigin==="anonymous"?o.credentials="omit":o.credentials="same-origin",o}function t(n){if(n.ep)return;n.ep=!0;const o=s(n);fetch(n.href,o)}})();const F=1e5,G=1e4,q=2e4,E=100,R=document.getElementById("app");if(!R)throw new Error("missing #app root");R.innerHTML=`
  <header class="topbar">
    <div class="wordmark">veil <span class="eyebrow">reversible PII masking</span></div>
    <button class="theme-toggle" id="theme-toggle" type="button">dark / light</button>
  </header>

  <main class="page-main">
  <section class="intro">
    <h1>Watch a prompt get <span class="accent">veiled</span>.</h1>
    <p class="lede">
      Paste text with personal data below. Everything runs locally, in this
      tab. The Python runtime downloads when you select Mask it; your prompt
      and vault stay here. Use fictional data to explore what the detectors catch.
    </p>
  </section>

  <section class="stage" data-stage="input">
    <label for="prompt">Your prompt</label>
    <textarea id="prompt" spellcheck="false" aria-describedby="input-limits"></textarea>

    <label for="known-persons">Known entities <span class="hint">(names your app already knows — from your CRM or user record)</span></label>
    <input id="known-persons" type="text" spellcheck="false" />
    <p class="note">
      veil detects emails, phones, cards, and the like by pattern — an
      arbitrary <em>name</em> needs a backend like this one, or an NER
      model. <a href="https://github.com/antonsoo/veil#features" target="_blank" rel="noreferrer">More in the README →</a>
    </p>

    <p class="note" id="input-limits">Demo limit: 100,000 characters in the prompt and 10,000 in known names; some symbols count twice. Longer input is rejected, never truncated.</p>
    <div class="actions">
      <button id="mask-btn" type="button">Mask it</button>
      <button id="stop-btn" class="secondary" type="button" hidden>Cancel</button>
      <button id="clear-btn" class="secondary" type="button">Clear private data</button>
    </div>
    <div class="status" id="load-status" role="status" aria-live="polite">Ready. Each prompt gets its own vault.</div>
  </section>

  <section class="stage" data-stage="masked" hidden>
    <h2><span class="step-label">masked prompt</span> what this prompt would send</h2>
    <pre class="panel" id="masked-output"></pre>
    <p class="note" id="preview-note"></p>
    <button id="download-masked" class="secondary" type="button">Download complete masked prompt</button>
  </section>

  <section class="stage" data-stage="vault" hidden>
    <h2><span class="step-label">vault</span> kept in this tab only</h2>
    <p class="note" id="vault-count"></p>
    <div class="table-scroll" role="region" aria-label="Vault mappings" tabindex="0">
    <table class="panel" id="vault-table" data-revealed="false">
      <thead>
        <tr><th>Type</th><th>Surrogate</th><th>Original</th></tr>
      </thead>
      <tbody></tbody>
    </table>
    </div>
    <button class="secondary" id="reveal-btn" type="button" aria-pressed="false">Reveal originals</button>
    <button class="secondary" id="download-vault" type="button">Download vault (contains originals)</button>
    <button id="simulate-btn" type="button">Simulate a model reply</button>
  </section>

  <section class="stage" data-stage="reply" hidden>
    <h2><span class="step-label">restored reply</span> streamed back through <code>Restorer</code></h2>
    <p class="note">Fictional reply using this prompt only. No model is called and no action is performed.</p>
    <pre class="panel" id="reply-output"></pre>
  </section>
  </main>

  <footer>
    Runs entirely client-side via <a href="https://pyodide.org" target="_blank" rel="noreferrer">Pyodide</a>.
    No prompt, reply, or vault ever leaves this browser tab.
    <a href="https://github.com/antonsoo/veil" target="_blank" rel="noreferrer">Source on GitHub →</a>
  </footer>
`;const r=e=>{const a=document.getElementById(e);if(!a)throw new Error(`missing #${e}`);return a},g=r("prompt"),b=r("known-persons"),L=r("mask-btn"),d=r("load-status"),T=r("masked-output").closest(".stage"),v=r("masked-output"),N=r("vault-table").closest(".stage"),I=r("vault-table"),x=I.querySelector("tbody"),C=r("reveal-btn"),M=r("simulate-btn"),k=r("reply-output").closest(".stage"),y=r("reply-output"),V=r("theme-toggle");g.value="Hi, this is Jordan Alvarez. My email is jordan.alvarez@example.com and my phone is 415-555-0132. Please charge card 4111 1111 1111 1111 for the renewal.";b.value="Jordan Alvarez";const O=r("stop-btn"),W=r("clear-btn"),J=r("download-masked"),z=r("download-vault"),A=r("preview-note"),j=r("vault-count");try{const e=localStorage.getItem("veil-theme");(e==="light"||e==="dark")&&(document.documentElement.dataset.theme=e)}catch{}V.addEventListener("click",()=>{const a=(document.documentElement.dataset.theme??(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"))==="dark"?"light":"dark";document.documentElement.dataset.theme=a;try{localStorage.setItem("veil-theme",a)}catch{}});let p=null,u=0,m=!1,w=!1,i=null,S="",h=!1,l=null;const B=()=>JSON.stringify([g.value,b.value]);function f(){L.disabled=m,O.hidden=!m,M.disabled=m||!w||i===null||S!==B()}function P(){u+=1,p?.terminate(),p=null,w=!1,l&&(clearTimeout(l.timer),l.reject(new DOMException("Cancelled","AbortError")),l=null),m=!1,f()}function $(e){if(!p){p=new Worker(new URL("/veil/assets/python.worker-BbGwCqMj.js",import.meta.url),{type:"module"});const s=p;s.onmessage=t=>{if(!(p!==s||t.data.id!==u||l?.id!==t.data.id)){if(t.data.kind==="status"){d.textContent=t.data.message;return}clearTimeout(l.timer),l.resolve(t.data),l=null}},s.onerror=t=>{t.preventDefault(),!(p!==s||!l)&&(clearTimeout(l.timer),l.reject(new Error("Couldn't start Python. Select Mask it to retry.")),l=null)}}const a=p;return new Promise((s,t)=>{const n=window.setTimeout(()=>{l?.id===e.id&&(l=null,t(new Error("Python took too long to respond. Select Mask it to retry.")))},12e4);l={id:e.id,resolve:s,reject:t,timer:n},a.postMessage(e)})}function K(e){v.replaceChildren();let a=Math.min(e.masked.length,q);a<e.masked.length&&/[\uD800-\uDBFF]/.test(e.masked[a-1]??"")&&(a-=1);const s=e.masked.slice(0,a),t=new Set(e.mappings.map(o=>o.surrogate));let n=0;for(const o of s.matchAll(/⟨[A-Z]+_\d+⟩/g)){if(!t.has(o[0]))continue;v.append(document.createTextNode(s.slice(n,o.index)));const c=document.createElement("span");c.className="tok",c.textContent=o[0],v.append(c),n=o.index+o[0].length}v.append(document.createTextNode(s.slice(n))),A.textContent=a<e.masked.length?`Preview shows the first ${a.toLocaleString()} text units. The download contains the complete masked prompt.`:"Complete masked prompt. Review it before sharing: detection can miss personal data."}function _(){if(x.replaceChildren(),!i)return;const e=i.mappings;for(const a of e.slice(0,E)){const s=document.createElement("tr");for(const[t,n]of[["type-cell",a.type],["surrogate-cell",a.surrogate],["original-cell",h?a.original:"Hidden"]]){const o=document.createElement("td");o.className=t,o.textContent=n,s.append(o)}x.append(s)}j.textContent=`${e.length.toLocaleString()} ${e.length===1?"mapping":"mappings"} in this prompt.`+(e.length>E?` Showing the first ${E}; the vault download includes all mappings.`:""),I.dataset.revealed=String(h),C.textContent=h?"Hide originals":"Reveal originals",C.setAttribute("aria-pressed",String(h))}function H(e,a){a===u&&(p?.terminate(),p=null,w=!1,d.textContent=e instanceof Error?e.message:"Couldn't process the prompt. Try again.")}async function X(){const e=g.value,a=b.value;if(!e.trim()){d.textContent="Enter a prompt to mask.",g.focus();return}if(e.length>F||a.length>G){d.textContent="Input exceeds the demo limits. Shorten it and try again; the previous result is unchanged.";return}const s=B(),t=++u;m=!0,f(),d.textContent="Preparing to mask locally…";try{const n=await $({id:t,kind:"mask",prompt:e,names:a,manifestUrl:new URL("/veil/veil-src.json",location.href).href});if(t!==u)return;if(n.kind==="error")throw new Error(n.message);if(n.kind!=="masked")throw new Error("Unexpected result. Try masking again.");i=n.result,S=s,w=!0,h=!1,K(i),_(),T.hidden=!1,N.hidden=!1,k.hidden=!0,y.textContent="",d.textContent=`Masked this prompt with ${i.mappings.length.toLocaleString()} mappings. Its vault is separate from earlier prompts.`}catch(n){H(n,t)}finally{t===u&&(m=!1,f())}}L.addEventListener("click",()=>{X()});function U(){m&&P(),y.textContent="",k.hidden=!0,d.textContent=i?"Input changed. The previous result remains below; mask again before simulating a reply.":"Input changed. Select Mask it to start.",f()}g.addEventListener("input",U);b.addEventListener("input",U);O.addEventListener("click",()=>{P(),y.textContent="",k.hidden=!0,d.textContent="Cancelled. Select Mask it when you're ready to continue.",L.focus()});W.addEventListener("click",()=>{P(),i=null,S="",h=!1,g.value="",b.value="",v.replaceChildren(),x.replaceChildren(),y.replaceChildren(),A.textContent="",j.textContent="",T.hidden=N.hidden=k.hidden=!0,d.textContent="Cleared the prompt, vault and reply from this session.",f(),g.focus()});C.addEventListener("click",()=>{h=!h,_()});function D(e,a,s){const t=URL.createObjectURL(new Blob([e],{type:s})),n=document.createElement("a");n.href=t,n.download=a,n.click(),setTimeout(()=>URL.revokeObjectURL(t),1e3)}J.addEventListener("click",()=>{i&&D(i.masked,"veil-masked.txt","text/plain;charset=utf-8")});z.addEventListener("click",()=>{i&&D(JSON.stringify({version:1,mappings:i.mappings},null,2),"veil-vault.json","application/json")});function Y(e){const a=o=>e.find(c=>c.type===o)?.surrogate,s=a("PERSON"),t=a("EMAIL"),n=s?`Hi ${s}.`:"Thanks for your message.";return t?`${n} The contact email in your message is ${t}.`:`${n} I've noted the details in your message.`}async function Z(){if(!i||M.disabled)return;const e=++u,a=Array.from(Y(i.mappings)),s=[];for(let t=0;t<a.length;t+=3)s.push(a.slice(t,t+3).join(""));m=!0,f(),y.textContent="",k.hidden=!1,d.textContent="Restoring a fictional reply from this prompt…";try{const t=await $({id:e,kind:"restore",chunks:s});if(e!==u)return;if(t.kind==="error")throw new Error(t.message);if(t.kind!=="restored")throw new Error("Mask this prompt again before simulating.");const n=matchMedia("(prefers-reduced-motion: reduce)").matches;for(const o of t.chunks){if(n||await new Promise(c=>setTimeout(c,45)),e!==u)return;y.textContent+=o}d.textContent="Fictional reply restored. No model was called."}catch(t){H(t,e)}finally{e===u&&(m=!1,f())}}M.addEventListener("click",()=>{Z()});f();
