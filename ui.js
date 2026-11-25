"use strict";
const $ = id => document.getElementById(id);
function node(tag, value, ...children) {
  const result = document.createElement(tag);
  if (value !== null && value !== undefined) result.textContent = value;
  result.append(...children);
  return result;
}
function button(label, fn) {
  const b = node("button",label);
  b.type="button";
  b.addEventListener("click",()=>run(fn,b));
  return b;
}
async function run(fn,b) {
  if(b) b.disabled=true;
  try { await fn(); } catch(error) { status(error.message,true); }
  finally { if(b) b.disabled=false; }
}
function status(message,error=false) {
  $("status").textContent=message;
  $("status").classList.toggle("error",error);
}
async function api(action,data) {
  const response=await fetch("/api/"+action,data===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
  const value=await response.json();
  if(!response.ok) throw Error(value.error || "Request failed.");
  return value;
}
let controller;
async function stream(action,data) {
  if(controller) controller.abort();
  const request=new AbortController();
  controller=request;
  $("cancel").hidden=false;
  $("answer").textContent="";
  if($("sources")) $("sources").replaceChildren();
  status("Waiting for local Ollama…");
  try {
    const response=await fetch("/api/"+action,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data),signal:request.signal});
    if(!response.ok) throw Error((await response.json()).error);
    const reader=response.body.getReader(), decoder=new TextDecoder();
    let pending="";
    while(true) {
      const {done,value}=await reader.read();
      pending+=decoder.decode(value,{stream:!done});
      let end;
      while((end=pending.indexOf("\n"))>=0) {
        const item=JSON.parse(pending.slice(0,end)); pending=pending.slice(end+1);
        if(item.error) throw Error(item.error);
        if(item.sources) showSources(item.sources);
        if(item.token) $("answer").textContent+=item.token;
      }
      if(done) break;
    }
    status("Response complete.");
  } catch(error) {
    if(error.name!=="AbortError") throw error;
    status("Response cancelled.");
  } finally {
    if(controller===request) {controller=null; $("cancel").hidden=true;}
  }
}
function option(select,value,label,selected=false) {
  const item=node("option",label); item.value=value; item.selected=selected; select.append(item);
}
function selectList(id,items,empty) {
  const select=$(id), current=select.value;
  select.replaceChildren();
  option(select,"",empty);
  for(const [value,label] of items) option(select,value,label,String(value)===current);
}
function form(id,fn) {
  $(id).addEventListener("submit",event=>{
    event.preventDefault();
    run(()=>fn(Object.fromEntries(new FormData(event.target)),event.target),event.submitter);
  });
}
function textBlock(parent,title,body) {
  const item=node("details",null,node("summary",title),node("pre",body));
  parent.append(item);return item;
}
function empty(parent,value) {parent.append(node("p",value));}
function download(name,text,type="text/plain") {
  const blob=text instanceof Blob?text:new Blob([text],{type});
  const a=node("a"); a.href=URL.createObjectURL(blob); a.download=name; a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href),1000);
}
function binary(file) {
  if(file.size>30_000_000) throw Error(file.name+" exceeds 30 MB.");
  return new Promise((resolve,reject)=>{
    const reader=new FileReader(); reader.onerror=()=>reject(reader.error);
    reader.onload=()=>resolve({name:file.name,data:reader.result.split(",")[1]});
    reader.readAsDataURL(file);
  });
}
function graph(container,edges,open) {
  container.replaceChildren();
  if(!edges.length) return empty(container,"No relationships match.");
  const ns="http://www.w3.org/2000/svg";
  const svg=document.createElementNS(ns,"svg");
  const visible=edges.slice(0,25);
  svg.setAttribute("viewBox","0 0 840 "+(visible.length*38+30));
  visible.forEach((edge,i)=>{
    const y=26+i*38;
    const line=document.createElementNS(ns,"path");
    line.setAttribute("d","M260 "+y+" H568");
    line.setAttribute("class","connection");
    svg.append(line);
    for(const [x,label,anchor] of [[245,edge.from,"end"],[414,edge.kind,"middle"],[587,edge.to,"start"]]) {
      const text=document.createElementNS(ns,"text");
      text.setAttribute("x",x); text.setAttribute("y",y+5); text.setAttribute("text-anchor",anchor);
      text.textContent=label.length>32?label.slice(0,29)+"…":label;
      const title=document.createElementNS(ns,"title"); title.textContent=label;text.append(title);
      if(open && x!==414) {
        text.setAttribute("tabindex","0"); text.setAttribute("role","button");
        text.addEventListener("click",()=>run(()=>open(label)));
        text.addEventListener("keydown",event=>{if(event.key==="Enter")run(()=>open(label));});
      }
      svg.append(text);
    }
  });
  container.append(svg);
  if(edges.length>visible.length) empty(container,"Showing "+visible.length+" of "+edges.length+" links. Filter to narrow the graph.");
}
async function loadModels() {
  const value=await api("models");
  if($("model")) selectList("model",value.chat.map(name=>[name,name]),"Automatic chat model");
  if($("embedding")) selectList("embedding",value.embedding.map(name=>[name,name]),"Automatic embedding model");
  const health=$("health");
  health.textContent=value.offline?"Ollama offline":value.chat.length+" chat · "+value.embedding.length+" embedding";
  health.dataset.online=String(!value.offline);
}
function showPane(id) {
  for(const pane of document.querySelectorAll("main > section")) pane.hidden=pane.id!==id;
  for(const tab of document.querySelectorAll("nav button[data-pane]")) tab.setAttribute("aria-current",String(tab.dataset.pane===id));
}
function metrics(parent,items) {
  parent.replaceChildren(...items.map(([label,value])=>node("div",null,node("strong",value),node("span",label))));
}
function today() {
  const now=new Date();return new Date(now-Date.parse("1970-01-01")-now.getTimezoneOffset()*60000).toISOString().slice(0,10);
}
function showSources(items) {
  const list=$("sources");list.replaceChildren();
  for(const [i,item] of items.entries()) textBlock(list,item.name?"[D"+item.id+"] "+item.name+" · "+item.section:
    "[S"+(i+1)+"] "+item.path+":"+item.start+"–"+item.end,item.text);
}

document.addEventListener("DOMContentLoaded",()=>{
  document.documentElement.dataset.theme=localStorage.getItem("theme") || (matchMedia("(prefers-color-scheme: light)").matches?"light":"dark");
  $("theme").addEventListener("click",()=>{
    document.documentElement.dataset.theme=document.documentElement.dataset.theme==="dark"?"light":"dark";
    localStorage.setItem("theme",document.documentElement.dataset.theme);
  });
  $("sidebar").addEventListener("click",()=>document.body.classList.toggle("collapsed"));
  $("health").addEventListener("click",()=>run(loadModels));
  for(const tab of document.querySelectorAll("nav button[data-pane]")) tab.addEventListener("click",()=>showPane(tab.dataset.pane));
  document.addEventListener("keydown",event=>{
    if(event.key==="/"&&!event.metaKey&&!event.ctrlKey&&!["INPUT","TEXTAREA","SELECT"].includes(document.activeElement.tagName)){
      const search=document.querySelector("section:not([hidden]) [type=search]");
      if(search){event.preventDefault();search.focus();}
    }
  });
  if($("cancel")) $("cancel").addEventListener("click",()=>controller?.abort());
  run(loadModels);
  run(startApp);
});
let repos=[], current, overview={files:[],edges:[],symbols:[],languages:{},entrypoints:[],duplicates:[]};
function needed(){if(!current) throw Error("Select a repository first.");return current.id;}
async function startApp(){
  for(const id of ["local","clone","zip"]) form(id,async(data,target)=>{
    status("Indexing repository…");
    const item=await api(id,id==="zip"?await binary($("zip-file").files[0]):data);
    target.reset();await loadRepos();await choose(item.id);
    status("Indexed "+item.files+" files.");showPane("analysis");
  });
  $("file-filter").addEventListener("input",renderFiles);
  $("edge-filter").addEventListener("input",renderGraph);
  $("edge-kind").addEventListener("change",renderGraph);
  $("report").addEventListener("click",()=>run(exportReport));
  $("export-graph").addEventListener("click",()=>run(()=>{
    const svg=$("edges").querySelector("svg");if(!svg) throw Error("No graph to export.");
    const copy=svg.cloneNode(true);
    copy.setAttribute("xmlns","http://www.w3.org/2000/svg");
    copy.querySelectorAll("path").forEach(line=>{line.setAttribute("stroke","#64748b");line.setAttribute("stroke-width","2");});
    download(current.name+"-graph.svg",new XMLSerializer().serializeToString(copy),"image/svg+xml");
  }));
  $("a-query").addEventListener("submit",event=>{
    event.preventDefault();
    run(async()=>{
      const data={...Object.fromEntries(new FormData(event.target)),repo:needed()};
      if(event.submitter?.value==="ask") await stream("ask",data);
      else {showSources(await api("search",data));$("answer").textContent="";status("Search complete.");}
    },event.submitter);
  });
  await loadRepos();
  if(repos.length) await choose(repos[0].id);
}
async function loadRepos(){
  repos=await api("repos");
  const target=$("repo-list");target.replaceChildren();
  for(const repo of repos) target.append(node("article",null,node("h3",repo.name),node("p",repo.origin),
    button("Inspect",async()=>{await choose(repo.id);showPane("analysis");}),
    button("Delete index",async()=>{if(confirm("Delete this local index?")){await api("delete",{repo:repo.id});await loadRepos();if(current?.id===repo.id)location.reload();}})));
  if(!repos.length)empty(target,"No repositories indexed yet.");
}
async function choose(id){
  current=repos.find(item=>item.id===id);
  overview=await api("overview",{repo:id});
  $("file-heading").textContent="Source";$("file-source").textContent="";
  $("scoped")?.remove();
  selectList("scope",overview.files.map(file=>[file.path,file.path]),"Entire repository");
  metrics($("a-metrics"),[["Indexed files",overview.files.length],["Symbols",overview.symbols.length],["Import and call links",overview.edges.length],["Entry points",overview.entrypoints.length]]);
  renderFiles();renderGraph();
  const symbols=$("symbols");symbols.replaceChildren();
  const list=[...overview.symbols].sort((a,b)=>(b.complexity||0)-(a.complexity||0));
  for(const item of list.slice(0,150)) symbols.append(node("p",null,button(item.name+" · "+item.file+":"+item.line+(item.complexity?" · CC "+item.complexity:""),()=>openFile(item.file,item.line))));
  if(!list.length) empty(symbols,"No indexed declarations.");
  const details=$("repo-details");details.replaceChildren();
  for(const [language,count] of Object.entries(overview.languages)){
    const bar=node("div");bar.className="bar";bar.style.width=(100*count/overview.files.length)+"%";
    details.append(node("div",language+" · "+count),bar);
  }
  textBlock(details,"Entry points",overview.entrypoints.join("\n")||"None detected.");
  textBlock(details,"Exact duplicate files",overview.duplicates.map(group=>group.join(" ↔ ")).join("\n")||"None detected.");
  textBlock(details,"Recent Git commits",current.commits||"No Git history in this snapshot.");
}
function renderFiles(){
  const list=$("files");list.replaceChildren();const q=$("file-filter").value.toLowerCase();
  for(const f of overview.files.filter(x=>x.path.toLowerCase().includes(q))) list.append(node("div",null,button(f.path,()=>openFile(f.path))));
  if(!list.children.length)empty(list,"No files match.");
}
async function openFile(path,line){
  if(!overview.files.some(x=>x.path===path))return;
  const item=await api("source",{repo:needed(),path});
  $("file-heading").textContent=path+(line?":"+line:"");
  const source=$("file-source");source.replaceChildren();
  item.code.split("\n").forEach((value,i)=>{
    const row=node("div",String(i+1).padStart(4)+"  "+value);
    if(i+1===line){row.id="active-line";row.style.background="var(--raised)";}
    source.append(row);
  });
  $("scope").value=path;showPane("analysis");
  if(line) $("active-line")?.scrollIntoView({block:"center"});
}
function renderGraph(){
  const q=$("edge-filter").value.toLowerCase(),kind=$("edge-kind").value;
  graph($("edges"),overview.edges.filter(x=>(!kind||x.kind===kind)&&(x.from+" "+x.to).toLowerCase().includes(q)),
        label=>openFile(label.split(" · ")[0]));
}
function exportReport(){
  needed();
  const lines=["# "+current.name,"","## Languages",...Object.entries(overview.languages).map(([name,n])=>"- "+name+" · "+n),
    "","## Entry points",...overview.entrypoints.map(x=>"- "+x),"","## Complexity hotspots",
    ...overview.symbols.filter(x=>x.complexity).sort((a,b)=>b.complexity-a.complexity).slice(0,30).map(x=>"- "+x.file+":"+x.line+" · "+x.name+" · "+x.complexity),
    "","## Recent commits","",current.commits];
  download(current.name+"-analysis.md",lines.join("\n"));
}
