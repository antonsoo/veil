const d="https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";let a=null;const r=n=>self.postMessage(n);async function u(n){const{loadPyodide:e}=await import(`${d}pyodide.mjs`),s=await e({indexURL:d}),t=await fetch(n,{redirect:"error"});if(!t.ok)throw new Error("source unavailable");const o=await t.json();for(const[l,m]of Object.entries(o)){const i=`/veil_src/${l}`;s.FS.mkdirTree(i.slice(0,i.lastIndexOf("/"))),s.FS.writeFile(i,m)}return await s.runPythonAsync(`
import sys, json
sys.path.insert(0, "/veil_src")
from veil import Masker
from veil.backends.known_entities import KnownEntitiesBackend
from veil.restore import Restorer

masker = None

def do_mask(text, names):
    global masker
    persons = [name.strip() for name in names.split(",") if name.strip()]
    candidate = Masker(name_backends=[KnownEntitiesBackend(persons=persons)])
    masked = candidate.mask(text)
    result = json.dumps({"masked": masked, "mappings": candidate.vault.to_dict()["mappings"]})
    masker = candidate
    return result

def restore_chunks(chunks_json):
    if masker is None:
        raise ValueError("mask a prompt first")
    restorer = Restorer(masker.vault)
    chunks = [restorer.feed(chunk) for chunk in json.loads(chunks_json)]
    chunks.append(restorer.flush())
    return json.dumps(chunks)
`),s}function c(n,e,...s){const t=n.globals.get(e);try{return t(...s)}finally{t.destroy()}}self.onmessage=async n=>{const e=n.data;let s=!1;try{if(e.kind==="mask"){if(e.prompt.length>1e5||e.names.length>1e4){r({id:e.id,kind:"error",message:"Input exceeds the demo limits. Shorten it and try again."});return}a||(r({id:e.id,kind:"status",message:"Loading Python for this tab… You can cancel."}),a=u(e.manifestUrl));const t=await a;s=!0,r({id:e.id,kind:"status",message:"Masking locally…"});const o=JSON.parse(c(t,"do_mask",e.prompt,e.names));r({id:e.id,kind:"masked",result:o})}else{if(!a)throw new Error("missing session");const t=await a;s=!0;const o=JSON.parse(c(t,"restore_chunks",JSON.stringify(e.chunks)));r({id:e.id,kind:"restored",chunks:o})}}catch{r({id:e.id,kind:"error",message:s?"Couldn't process this input. Shorten it or clear the session, then try again.":"Couldn't load Python. Check your connection and select Mask it to retry."})}};
