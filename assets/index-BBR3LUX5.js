(function(){const n=document.createElement("link").relList;if(n&&n.supports&&n.supports("modulepreload"))return;for(const t of document.querySelectorAll('link[rel="modulepreload"]'))o(t);new MutationObserver(t=>{for(const s of t)if(s.type==="childList")for(const r of s.addedNodes)r.tagName==="LINK"&&r.rel==="modulepreload"&&o(r)}).observe(document,{childList:!0,subtree:!0});function a(t){const s={};return t.integrity&&(s.integrity=t.integrity),t.referrerPolicy&&(s.referrerPolicy=t.referrerPolicy),t.crossOrigin==="use-credentials"?s.credentials="include":t.crossOrigin==="anonymous"?s.credentials="omit":s.credentials="same-origin",s}function o(t){if(t.ep)return;t.ep=!0;const s=a(t);fetch(t.href,s)}})();const R="0.26.4",x=`https://cdn.jsdelivr.net/pyodide/v${R}/full/`,C=document.getElementById("app");if(!C)throw new Error("missing #app root");C.innerHTML=`
  <header class="topbar">
    <div class="wordmark">veil <span class="eyebrow">reversible PII masking</span></div>
    <button class="theme-toggle" id="theme-toggle" type="button">dark / light</button>
  </header>

  <section class="intro">
    <h1>Watch a prompt get <span class="accent">veiled</span>.</h1>
    <p class="lede">
      Paste text with personal data below. Everything runs locally, in this
      tab: the real <code>veil</code> Python package runs on Pyodide
      (CPython compiled to WebAssembly), and nothing is sent anywhere.
    </p>
  </section>

  <section class="stage" data-stage="input">
    <label for="prompt">Your prompt</label>
    <textarea id="prompt" spellcheck="false"></textarea>

    <label for="known-persons">Known entities <span class="hint">(names your app already knows — from your CRM or user record)</span></label>
    <input id="known-persons" type="text" spellcheck="false" />
    <p class="note">
      veil detects emails, phones, cards, and the like by pattern — an
      arbitrary <em>name</em> needs a backend like this one, or an NER
      model. <a href="https://github.com/antonsoo/veil#features" target="_blank" rel="noreferrer">More in the README →</a>
    </p>

    <button id="mask-btn" type="button">Mask it</button>
    <div class="status" id="load-status">Loading Pyodide…</div>
  </section>

  <section class="stage" data-stage="masked" hidden>
    <h2><span class="step-label">masked prompt</span> what the model actually sees</h2>
    <pre class="panel" id="masked-output"></pre>
  </section>

  <section class="stage" data-stage="vault" hidden>
    <h2><span class="step-label">vault</span> kept in this tab only</h2>
    <table class="panel" id="vault-table" data-revealed="false">
      <thead>
        <tr><th>Type</th><th>Surrogate</th><th>Original</th></tr>
      </thead>
      <tbody></tbody>
    </table>
    <button class="secondary" id="reveal-btn" type="button">Reveal originals</button>
    <button id="simulate-btn" type="button">Simulate a model reply</button>
  </section>

  <section class="stage" data-stage="reply" hidden>
    <h2><span class="step-label">restored reply</span> streamed back through <code>Restorer</code></h2>
    <pre class="panel" id="reply-output"></pre>
  </section>

  <footer>
    Runs entirely client-side via <a href="https://pyodide.org" target="_blank" rel="noreferrer">Pyodide</a>.
    No prompt, reply, or vault ever leaves this browser tab.
    <a href="https://github.com/antonsoo/veil" target="_blank" rel="noreferrer">Source on GitHub →</a>
  </footer>
`;const l=e=>{const n=document.getElementById(e);if(!n)throw new Error(`missing #${e}`);return n},b=l("prompt"),M=l("known-persons"),h=l("mask-btn"),k=l("load-status"),$=l("masked-output").closest(".stage"),p=l("masked-output"),L=l("vault-table").closest(".stage"),m=l("vault-table"),P=m.querySelector("tbody"),v=l("reveal-btn"),g=l("simulate-btn"),S=l("reply-output").closest(".stage"),u=l("reply-output"),_=l("theme-toggle");b.value="Hi, this is Jordan Alvarez. My email is jordan.alvarez@example.com and my phone is 415-555-0132. Please charge card 4111 1111 1111 1111 for the renewal.";M.value="Jordan Alvarez";function O(){return M.value.split(",").map(e=>e.trim()).filter(e=>e.length>0)}function I(){const e=localStorage.getItem("veil-theme");(e==="light"||e==="dark")&&(document.documentElement.dataset.theme=e)}I();_.addEventListener("click",()=>{const n=(document.documentElement.dataset.theme??(window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"))==="dark"?"light":"dark";document.documentElement.dataset.theme=n,localStorage.setItem("veil-theme",n)});let y=null;async function w(){return y||(y=N()),y}async function N(){const e=document.createElement("script");e.src=`${x}pyodide.js`;const n=new Promise((s,r)=>{e.onload=()=>s(),e.onerror=()=>r(new Error("failed to load Pyodide from CDN"))});document.head.appendChild(e),await n;const a=await loadPyodide({indexURL:x});k.textContent="Fetching veil source…";const t=await(await fetch("/veil/veil-src.json")).json();for(const[s,r]of Object.entries(t)){const i=`/veil_src/${s}`,c=i.slice(0,i.lastIndexOf("/"));a.FS.mkdirTree(c),a.FS.writeFile(i,r)}return await a.runPythonAsync(`
import sys, json
sys.path.insert(0, "/veil_src")
from veil import Masker
from veil.backends.known_entities import KnownEntitiesBackend
from veil.restore import Restorer

# The known-entities backend is the first-class way veil finds names: the
# application (here, the demo page) supplies identities it already knows,
# rather than guessing from free text. See do_mask() below for how the
# "Known entities" field feeds this on every call.
known = KnownEntitiesBackend()
masker = Masker(name_backends=[known])

def do_mask(text, persons_json):
    known.persons = json.loads(persons_json)
    masked = masker.mask(text)
    mappings = [
        {"type": m.type.value, "surrogate": m.surrogate, "original": m.original}
        for m in masker.vault.mappings()
    ]
    return json.dumps({"masked": masked, "mappings": mappings})

def make_restorer():
    return Restorer(masker.vault)
`),k.textContent="",h.disabled=!1,a}h.disabled=!0;w().then(()=>{h.disabled=!1}).catch(e=>{k.textContent=`Couldn't load Pyodide: ${String(e)}`});function T(e,n){if(p.innerHTML="",n.length===0){p.textContent=e;return}const a=new RegExp(`(${n.map(j).join("|")})`,"g"),o=e.split(a);for(const t of o)if(n.includes(t)){const s=document.createElement("span");s.className="tok",s.textContent=t,p.appendChild(s)}else p.appendChild(document.createTextNode(t))}function j(e){return e.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")}function H(e){P.innerHTML="";for(const n of e){const a=document.createElement("tr");a.innerHTML=`
      <td class="type-cell">${n.type}</td>
      <td class="surrogate-cell">${n.surrogate}</td>
      <td class="original-cell">${A(n.original)}</td>
    `,P.appendChild(a)}m.dataset.revealed="false",v.textContent="Reveal originals"}function A(e){const n=document.createElement("div");return n.textContent=e,n.innerHTML}h.addEventListener("click",()=>{(async()=>{const a=(await w()).globals.get("do_mask")(b.value,JSON.stringify(O())),o=JSON.parse(a),t=o.mappings.map(s=>s.surrogate);T(o.masked,t),H(o.mappings),$.hidden=!1,L.hidden=!1,S.hidden=!0,u.textContent=""})()});v.addEventListener("click",()=>{const e=m.dataset.revealed==="true";m.dataset.revealed=e?"false":"true",v.textContent=e?"Reveal originals":"Hide originals"});function B(e){const n=r=>e.find(i=>i.type===r)?.surrogate,a=n("PERSON"),o=n("EMAIL"),t=e.some(r=>r.type==="CARD"),s=a?`Hi ${a}, thanks`:"Thanks";return t&&o?`${s} — I've updated the card on file and will send a receipt to ${o}.`:o?`${s} — I've noted your details and will follow up at ${o} shortly.`:`${s} — I've noted the details and will follow up shortly.`}g.addEventListener("click",()=>{(async()=>{const e=await w(),a=e.globals.get("do_mask")(b.value,JSON.stringify(O())),o=JSON.parse(a),t=B(o.mappings);S.hidden=!1,u.textContent="",g.disabled=!0;const r=e.globals.get("make_restorer")();let i=0;const c=(d,f)=>Math.floor(d+Math.random()*(f-d+1)),E=()=>{if(i>=t.length){u.textContent+=r.flush(),r.destroy(),g.disabled=!1;return}const d=c(2,6),f=t.slice(i,i+d);i+=d,u.textContent+=r.feed(f),setTimeout(E,c(30,90))};E()})()});
