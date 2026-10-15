(function(){
const clone = value => JSON.parse(JSON.stringify(value));
// A versioned in-memory Firestore double. Transactions retry on version conflicts,
// stage writes until commit, and can fail before commit. No network or production data.
function createTestFirestore() {
  const state = {
    gameId: 'test-game', members: [1,2,3,4,5].map(n => ({id:`p${n}`,name:`Player ${n}`})),
    races: [{id:'r1',no:1,type:'prelim',runners:['p1','p2','p3','p4'],status:'open',closeAt:null,settle:null}], cur:0,
  };
  const data = {
    'game/state': state, 'game/history': {races:[]}, 'game/roster': {players:[]},
    'game/ledger': {entries:[1,2,3,4,5].map(n => ({member:`p${n}`,gameId:'test-game',amt:1000}))},
    'bets/device': {member:'p5',tickets:[]},
  };
  const versions = {}, listeners = [], collections = [];
  const b = {data, fail:null, gate:null, attempts:0, commits:0};
  const read = p => ({id:p.split('/').pop(), exists:!!data[p], data:()=>clone(data[p])});
  const notify = () => {
    listeners.forEach(([p,fn])=>fn(read(p)));
    const docs=Object.keys(data).filter(p=>p.startsWith('bets/')).map(p=>read(p));
    collections.forEach(fn=>fn({docs}));
  };
  b.notify=notify;
  const write = (p,v) => {data[p]=clone(v); versions[p]=(versions[p]||0)+1;};
  const failIfRequested = () => { if(b.fail) { const e=b.fail; b.fail=null; throw e; } };
  b.firestore = {
    doc: p => ({path:p, get:async()=>read(p), onSnapshot:fn=>{listeners.push([p,fn]); queueMicrotask(()=>fn(read(p))); return ()=>{};}, set:async v=>{
      if(b.gate) await b.gate; failIfRequested(); write(p,v); notify();
    }}),
    collection: () => ({onSnapshot:fn=>{collections.push(fn); queueMicrotask(notify); return ()=>{};}}),
    runTransaction: async fn => {
      for(let attempt=0; attempt<10; attempt++) {
        b.attempts++;
        if(b.gate) await b.gate;
        const reads={}, staged={};
        const result = await fn({
          get:async ref=>{ reads[ref.path]=versions[ref.path]||0; return read(ref.path); },
          set:(ref,v)=>{staged[ref.path]=clone(v);},
        });
        failIfRequested();
        if(Object.keys(reads).some(p=>reads[p] !== (versions[p]||0))) continue;
        Object.entries(staged).forEach(([p,v])=>write(p,v));
        b.commits++; notify(); return result;
      }
      throw new Error('Too many conflicts');
    },
  };
  return b;
}

if(typeof module !== 'undefined') module.exports=createTestFirestore;
else globalThis.createTestFirestore=createTestFirestore;
})();
