"""Write flow/ui/demo.html: the UI with a fake backend, so the design can be browsed outside the app (not shipped)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from flow import styles
root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "flow", "ui")
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
window.pywebview={api:{status:async()=>({state:'trial',days_left:14,version:'0.6',machine:'demo'}),load_session:async()=>null, styles:async()=>STYLES,
 pick_reference:async()=>'/Users/harel/Desktop/הפקה/tps/TPS - Oasis.wav',
 analyze:async()=>{await wait(900);return {ok:true,ref:{bpm:124,key:{tonic:'A',mode:'minor',confidence:.8},duration:290,bars:144,sections:secs,tempo_info:{source:'estimated'},overview:Array.from({length:720},(_,i)=>{const b=Math.floor(i/5);const e=en[Math.min(143,b)]||.3;return Math.min(1,e*(.55+.45*Math.abs(Math.sin(i*.7)))*(.8+.2*Math.random()));}),elements:{energy:en,kick:en.map(v=>v>.4),hats:en.map(v=>v>.5)}}}},
 pick_folders:async()=>'/Users/harel/Desktop/הפקה/tps/TPS - Oasis - Sample Pack',
 scan_pack:async()=>{await wait(900);return {ok:true,pack:{count:255,by_role:{kick:12,clap:8,chat:20,synth:30,bass:15,atmos:9,perc:22,fx:14},warnings:[],bpm_hint:124}}},
 pick_vocal:async()=>'/Users/harel/Music/Vocals/Chant - Yalla 122 BPM Amin.wav',
 analyze_vocal:async()=>{await wait(700);return {ok:true,vocal:{name:'Chant - Yalla 122 BPM Amin.wav',duration:38.2,bpm:122,key:{pc:9,mode:'minor',source:'name'},count:7}}},
 ableton_status:async()=>({ok:true,fresh:true,tracks:2}),
 finish_options:async()=>[{key:'gain',name:'Gain staging',hint:'Every track at a sensible level relative to the kick, with Utility.',on:true},{key:'lowcut',name:'Clean low end',hint:'A high-pass on everything that is not kick or bass.',on:true},{key:'duck',name:'Sidechain pump',hint:'Your sidechain plug-in on every track except the kick; without one, Auto Pan does the ducking.',on:true},{key:'space',name:'Space',hint:'Reverb on pads, atmospheres, claps, vocal and synth.',on:true},{key:'glue',name:'Drum glue',hint:'Drum Buss on claps, percussion and toms.',on:true},{key:'transitions',name:'Transition sweeps',hint:'The eight bars before each drop get a rising sweep on every loop.',on:true}],
 scan_plugins:async()=>({ok:true,plugins:{count:20,synths:['Serum'],sidechain:['Kickstart 2']}}),
 build:async()=>{ (async()=>{ await wait(800); window.flowProgress('Listening to the reference',.05); await wait(900); window.flowProgress('Choosing sounds',.2); await wait(900); window.flowPlan({bars:144,bpm:124,sections:secs,layers}); window.flowProgress('Rendering patterns',.35);
   for(let i=0;i<layers.length;i++){ await wait(600); window.flowProgress('Placing clips: '+layers[i].name,.45+i*.04); window.flowProgress('@track:'+i,.5); }
   window.flowProgress('Finishing: Utility, EQ Eight',.9); await wait(1200); window.flowDone({bars:144,bpm:124,sections:secs,layers,rows,placeholders:['Bass','Synth'],export:null,ableton:{warnings:[]}}); })(); return {ok:true}; },
 open_path:async()=>({ok:true}), pick_folder:async()=>'/Users/harel/Music/FLOW', install_bridge:async()=>({ok:true,path:'~/Music/Ableton/User Library/Remote Scripts/FLOW',steps:[]}), activate:async()=>({ok:true})}};
window.dispatchEvent(new Event('pywebviewready'));
})();
</script>
</body>""" % json.dumps(styles.listing(), ensure_ascii=False)
open(os.path.join(root, "demo.html"), "w", encoding="utf-8").write(s.replace("</body>", mock, 1))
print("demo.html written")
