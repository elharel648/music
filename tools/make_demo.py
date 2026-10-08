"""Write flow/ui/demo.html: the UI with a fake backend, so the design can be browsed outside the app (not shipped)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from flow import styles
root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "flow", "ui")
# a 30 s stand-in for the preview mix: kick on every beat at 124 BPM, a hat on the off-beats
import numpy as np, soundfile as sf
sr, bpm, secs = 22050, 124, 30
t = np.arange(int(sr * secs)) / sr
beat = 60 / bpm
y = np.zeros_like(t)
for k in range(int(secs / beat)):
    i = int(k * beat * sr); n = int(0.18 * sr); tt = np.arange(n) / sr
    y[i:i + n] += np.sin(2 * np.pi * (55 + 90 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 9) * 0.8
    j = int((k + 0.5) * beat * sr); m = int(0.05 * sr)
    y[j:j + m] += np.random.default_rng(k).standard_normal(m) * np.exp(-np.arange(m) / sr * 90) * 0.12
sf.write(os.path.join(root, "demo-preview.wav"), np.clip(y, -1, 1), sr, subtype="PCM_16")
s = open(os.path.join(root, "index.html"), encoding="utf-8").read()
mock = r"""
<script>
/* demo: fake backend so the UI can be browsed outside the app */
(function(){
const STYLES = %s;
const secs=[{label:'Intro',start:1,end:17,bars:16},{label:'Groove',start:17,end:41,bars:24},{label:'Drop',start:41,end:73,bars:32},{label:'Breakdown',start:73,end:89,bars:16},{label:'Build',start:89,end:97,bars:8},{label:'Drop 2',start:97,end:129,bars:32},{label:'Outro',start:129,end:145,bars:16}];
const en=Array.from({length:144},(_,i)=>{const s=secs.find(s=>i+1>=s.start&&i+1<s.end);return {Intro:.2,Groove:.5,Drop:.9,Breakdown:.25,Build:.6,'Drop 2':1,Outro:.3}[s.label]+Math.sin(i)*.04});
const layers=[['Kick','kick',[[1,73],[97,129],[129,143]]],['Clap','clap',[[41,73],[97,129]]],['Closed Hat','chat',[[17,73],[97,129]]],['Perc Loop','perc_loop',[[17,73],[97,129]]],['Bass','bass',[[17,73],[97,129],[129,141]]],['Synth','synth',[[17,89],[97,129]]],['Pad','pad',[[1,97]]],['Atmosphere','atmos',[[1,145]]],['Vocal','vocal',[[49,53],[55,59],[73,77],[79,81],[83,87],[105,109],[111,113]]],['Impact','impact',[],[40.875,96.875]],['Uplifter','uplifter',[],[93]]].map((a,i)=>({i,name:a[0],role:a[1],spans:a[2],hits:a[3]||[],sweeps:[],sweep_bars:8})); layers[4].sweeps=[33];
const rows=secs.map(s=>({label:s.label,start:s.start,end:s.end,bars:s.bars,layers:layers.filter(l=>l.spans.some(([a,b])=>a<=s.start&&s.start<b)).map(l=>l.name),enter:[],leave:[]}));
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const Q=new URLSearchParams(location.search);
const GROUPS=[['Kick',12],['Clap',8],['Closed Hat',20],['Open Hat',6],['Tom',10],['Perc',22],['Shaker Loop',4],['Perc Loop',8],['Bass Shot',15],['Synth Shot',30],['Atmosphere',9],['Ambience',6],['Impact',5],['Uplifter',5],['Downlifter',4],['FX',91]];
const SAMPLES=[]; GROUPS.forEach(([g,n])=>{ for(let i=1;i<=n;i++) SAMPLES.push({name:`TPS - Oasis - ${g} ${String(i).padStart(2,'0')}${/Loop/.test(g)?' (120 BPM)':''}.wav`, path:`/pack/${g.replace(/\s/g,'')}-${i}.wav`, rel:`${g}/${g} ${i}.wav`, duration:.6, bpm:/Loop/.test(g)?120:null, is_loop:/Loop/.test(g)}); });
const GIDX=(g)=>SAMPLES.map((s,i)=>s.name.includes(`- ${g} `)?i:-1).filter(i=>i>=0);
window.pywebview={api:{status:async()=>(window.__lic?{state:'licensed',email:'you@studio.com',expires:null,version:'0.8.4',machine:'demo'}:(Q.has('expired')?{state:'expired',days_left:0,version:'0.8.4',machine:'demo'}:{state:'trial',days_left:14,version:'0.8.4',machine:'demo'})),load_session:async()=>null, styles:async()=>STYLES,
 pick_reference:async()=>'/Users/harel/Desktop/הפקה/tps/TPS - Oasis.wav',
 analyze:async()=>{await wait(900);return {ok:true,ref:{bpm:124,key:{tonic:'A',mode:'minor',confidence:.8},duration:290,bars:144,sections:secs,tempo_info:{source:'estimated'},overview:Array.from({length:720},(_,i)=>{const b=Math.floor(i/5);const e=en[Math.min(143,b)]||.3;return Math.min(1,e*(.55+.45*Math.abs(Math.sin(i*.7)))*(.8+.2*Math.random()));}),elements:{energy:en,kick:en.map(v=>v>.4),hats:en.map(v=>v>.5)}}}},
 pick_folders:async()=>'/Users/harel/Desktop/הפקה/tps/TPS - Oasis - Sample Pack',
 scan_pack:async()=>{await wait(900);return {ok:true,pack:{count:255,by_role:{kick:12,clap:8,chat:20,synth:30,bass:15,atmos:9,perc:22,fx:14},warnings:[],bpm_hint:124,samples:SAMPLES}}},
 kit_options:async(folder,bpm,ov)=>{ await wait(600); const mk=(role,label,g,pick)=>{ const c=GIDX(g).slice(0,24).map(i=>SAMPLES[i]); const ch=(ov&&ov[role])?(c.find(x=>x.path===ov[role])||{name:ov[role].split('/').pop(), path:ov[role], rel:ov[role].split('/').pop(), duration:.6, bpm:null, is_loop:false, external:true}):c[pick||0]; return {role,label,chosen:ch,candidates:c}; };
   return {ok:true,bpm:124,kit:[mk('kick','Kick','Kick',7),mk('clap','Clap','Clap',3),mk('chat','Closed hat','Closed Hat',6),mk('ohat','Open hat','Open Hat',2),mk('tom','Tom','Tom',4),mk('perc','Perc','Perc'),mk('shaker_loop','Shaker loop','Shaker Loop'),mk('perc_loop','Perc loop','Perc Loop'),mk('perc_loop2','Perc loop 2','Perc Loop',1),mk('bass','Bass','Bass Shot',3),mk('synth','Synth','Synth Shot',1),mk('pad','Pad','Atmosphere'),mk('atmos','Atmosphere','Ambience'),mk('impact','Impact','Impact'),mk('uplifter','Uplifter','Uplifter'),mk('downlifter','Downlifter','Downlifter')]}; },
 audition_url:async(p)=>({ok:true,url:'demo-preview.wav'}),
 sample_peaks:async(p)=>{ await wait(120); let h=0; for(const c of p) h=(h*31+c.charCodeAt(0))>>>0; const loop=/Loop|Atmos|Ambience/.test(p); return {ok:true,peaks:Array.from({length:48},(_,i)=>{ const x=i/48; const env=loop?(.45+.4*Math.abs(Math.sin(x*9+h%%7))):Math.exp(-x*(3+h%%5)); const r=Math.abs(Math.sin(i*12.9898+h))*.6+.4; return Math.min(1,env*r+ (i===0?.2:0)); })}; },
 preview:async(opts)=>{ (async()=>{ await wait(700); window.flowProgress('Measuring the reference',.05); await wait(600); window.flowProgress('From your sounds: 16 roles',.2); await wait(600); window.flowPlan({bars:144,bpm:124,sections:secs,layers}); window.flowProgress('Arranged: 144 bars, 11 tracks',.4); for(let i=0;i<layers.length;i++){ await wait(250); window.flowProgress('Mixing '+layers[i].name,.4+.6*(i+1)/layers.length); window.flowProgress('@track:'+i,.5); } await wait(300); window.flowPreview({url:'demo-preview.wav',seconds:30,bars:144,bpm:124,structure:S.structure,used:11}); })(); return {ok:true}; },
 pick_vocal:async()=>'/Users/harel/Music/Vocals/Chant - Yalla 122 BPM Amin.wav',
 analyze_vocal:async()=>{await wait(700);return {ok:true,vocal:{name:'Chant - Yalla 122 BPM Amin.wav',duration:38.2,bpm:122,key:{pc:9,mode:'minor',source:'name'},count:7}}},
 ableton_status:async()=>({ok:true,fresh:!window.__built,tracks:window.__built?16:2,bridge:'3',bridge_outdated:Q.has('oldbridge'),rebuild:!!window.__built,alma_tracks:14}),
 finish_options:async()=>[{key:'gain',name:'Gain staging',hint:'Every track at a sensible level relative to the kick, with Utility.',on:true},{key:'lowcut',name:'Clean low end',hint:'A high-pass on everything that is not kick or bass.',on:true},{key:'duck',name:'Sidechain pump',hint:'Your sidechain plug-in on every track except the kick; without one, Auto Pan does the ducking.',on:true},{key:'space',name:'Space',hint:'Reverb on pads, atmospheres, claps, vocal and synth.',on:true},{key:'glue',name:'Drum glue',hint:'Drum Buss on claps, percussion and toms.',on:true},{key:'transitions',name:'Transition sweeps',hint:'The eight bars before each drop get a rising sweep on every loop.',on:true}],
 scan_plugins:async()=>({ok:true,plugins:{count:20,synths:['Serum'],sidechain:['Kickstart 2']}}),
 build:async()=>{ if(Q.has('fail')){ (async()=>{ await wait(1500); window.flowProgress('Listening to the reference',.05); await wait(900); window.flowError('Ableton Live is not reachable. Open Live, enable the Alma Bridge control surface (Settings › Link, Tempo & MIDI), and keep a Live Set in front.'); })(); return {ok:true}; } (async()=>{ await wait(800); window.flowProgress('Listening to the reference',.05); await wait(900); window.flowProgress('Choosing sounds',.2); await wait(900); window.flowPlan({bars:144,bpm:124,sections:secs,layers}); window.flowProgress('Rendering patterns',.35);
   for(let i=0;i<layers.length;i++){ await wait(600); window.flowProgress('Placing clips: '+layers[i].name,.45+i*.04); window.flowProgress('@track:'+i,.5); }
   window.flowProgress('Finishing: Utility, EQ Eight',.9); await wait(1200); window.flowDone({bars:144,bpm:124,sections:secs,layers,rows,placeholders:['Bass','Synth'],export:null,ableton:{warnings:[]},structure:S.structure,style_name:(S.styles.find(x=>x.key===S.style)||{}).name,kit:Object.fromEntries(layers.slice(0,8).map(l=>[l.role,l.name]))}); if(!S.preview||S.previewStale){ await wait(2500); window.flowPreview({url:'demo-preview.wav',seconds:30,bars:144,bpm:124,structure:S.structure,used:8}); } })(); return {ok:true}; },
 open_path:async()=>({ok:true}), pick_folder:async()=>'/Users/harel/Music/Alma', install_bridge:async()=>({ok:true,path:'~/Music/Ableton/User Library/Remote Scripts/Alma',steps:[]}), activate:async(k)=>{ await wait(500); if(!/^ALMA-/.test(k)) return {ok:false,error:'This is not an Alma key.'}; window.__lic=true; return {ok:true,email:'you@studio.com'}; }, apply_swaps:async(o)=>{ (async()=>{ await wait(700); window.flowProgress('Replacing Clap \u00b7 Clap 04',.3); await wait(1100); window.flowSwapped({replaced:['clap'],names:['Clap \u00b7 Clap 04'],notes:[]}); })(); return {ok:true}; }, install_update:async()=>{ await wait(800); return {ok:true}; }, pick_sample:async()=>{ await wait(600); return '/Users/harel/Music/Found Sounds/My Kick 02.wav'; }, send_feedback:async(n)=>{ await wait(700); return {ok:true, sent:false, path:'/Users/harel/Desktop/Alma feedback 2026-10-08 1530.json'}; }}};
window.dispatchEvent(new Event('pywebviewready'));
if(Q.has('update')){ (async()=>{ await wait(2000); const base={available:true,version:'0.9.0',url:'https://alma-e5db0.web.app/#access',notes:'Demo update',required:Q.has('required')}; for(let p=0;p<=100;p+=20){ window.flowUpdate({...base,state:'downloading',pct:p}); await wait(350); } window.flowUpdate({...base,state:'ready',pct:100}); })(); }

/* site: ?auto=1 runs the whole flow by itself until the visitor touches anything; ?state=ref|snd|dir|built jumps there (screenshots) */
const origDone=window.flowDone; window.flowDone=s=>{ window.__built=true; return origDone(s); };
const stop={v:false}; document.addEventListener('pointerdown',()=>{stop.v=true;},{capture:true,once:true}); document.addEventListener('keydown',()=>{stop.v=true;},{capture:true,once:true});
const go=async(ms,fn)=>{ await wait(ms); if(stop.v) return false; fn(); return true; };
if(Q.has('auto')){ (async()=>{ await wait(1200);
  if(!await go(0,()=>$('pickRef').click())) return; if(!await go(3200,()=>$('pickPack').click())) return; if(!await go(4200,()=>setActive('dir'))) return;
  if(!await go(1600,()=>stepStyle(1))) return; if(!await go(1300,()=>stepStyle(1))) return; if(!await go(1800,()=>startBuild())) return;
  if(!await go(9500,()=>{ const b=$('listenBtn'); if(b && !b.classList.contains('hidden')) b.click(); })) return;
  await wait(16000); if(!stop.v) location.replace(location.pathname+location.search); })(); }
const st=Q.get('state');
if(st){ (async()=>{ await wait(500); $('pickRef').click(); if(st==='ref') return; await wait(2200); $('pickPack').click(); if(st==='snd') return; await wait(3000); setActive('dir'); if(st==='dir') return; await wait(600); startBuild(); })(); }
})();
</script>
</body>""" % json.dumps(styles.listing(), ensure_ascii=False)
html = s.replace("</body>", mock, 1)
open(os.path.join(root, "demo.html"), "w", encoding="utf-8").write(html)
print("demo.html written")
if "--site" in sys.argv:
    import shutil
    site = os.path.join(os.path.dirname(root), "..", "site", "demo")
    os.makedirs(site, exist_ok=True)
    open(os.path.join(site, "index.html"), "w", encoding="utf-8").write(html.replace("<title>Alma</title>", "<title>Alma demo</title>"))
    shutil.copytree(os.path.join(root, "fonts"), os.path.join(site, "fonts"), dirs_exist_ok=True)
    shutil.copy(os.path.join(root, "demo-preview.wav"), os.path.join(site, "demo-preview.wav"))
    print("site/demo written")
