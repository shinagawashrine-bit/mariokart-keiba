const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const clone = value => JSON.parse(JSON.stringify(value));
const html = fs.readFileSync(process.env.KEIBA_TEST_HTML || path.join(root, 'index.html'), 'utf8');
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1].split('/* ---------------- events')[0];
const shim = fs.readFileSync(path.join(root, 'shim.js'), 'utf8');

const backend = require('./fake-firestore.js');
async function app(b=backend()) {
  const messages=[];
  const context = vm.createContext({
    console:{error(){}}, messages,
    location:{origin:'http://test.invalid',pathname:'/',hash:'#bet'},
    document:{addEventListener(){}}, addEventListener(){},
    localStorage:{getItem(){return null;},setItem(){}},
    MK_CONFIG:{firebase:{apiKey:'local-test'}},
    firebase:{apps:[{}],firestore:()=>b.firestore},
  });
  context.window=context;
  vm.runInContext(shim,context);
  vm.runInContext(source + '\nrender=()=>{}; toast=m=>messages.push(m); play=()=>{}; globalThis.app={S,A,mutateLedger,mutateState};', context);
  const a=context.app;
  a.S.db=await context.claude.use('db');
  a.S.state=clone(b.data['game/state']); a.S.history=clone(b.data['game/history']);
  a.S.ledger=clone(b.data['game/ledger']); a.S.roster={players:[]};
  a.S.bets={device:clone(b.data['bets/device'])}; a.S.uid='device'; a.S.isOwner=true; a.S.ready=true;
  a.S.ui.sel=['p1']; a.S.ui.amt=100;
  return {...a,b,messages,context};
}
function offline(a) {a.b.fail=Object.assign(new Error('Simulated denial'),{code:'permission-denied'});}
function closed(a) { a.S.state.races[0].status='closed'; a.S.state.races[0].closeAt=Date.now(); a.b.data['game/state']=clone(a.S.state); a.S.ui.order=['p1','p2','p3']; }

test('failed bet does not change balance, tickets, selection, or report success; retry works',async()=>{
  const a=await app(); offline(a);
  await a.A.bet(); await new Promise(setImmediate);
  assert.equal(a.S.bets.device.tickets.length,0);
  assert.equal(a.b.data['bets/device'].tickets.length,0);
  assert.deepEqual(a.S.ui.sel,['p1']);
  assert.ok(!a.messages.some(m=>m.includes('賭けました')));
  assert.match(a.messages.at(-1),/権限/);
  await a.A.bet();
  assert.equal(a.b.data['bets/device'].tickets.length,1);
  assert.equal(a.S.bets.device.tickets.length,1);
  assert.equal(a.S.ui.sel.length,0);
  assert.match(a.messages.at(-1),/賭けました/);
});

test('double-clicking self bet submits once and does not update before acknowledgment',async()=>{
  const a=await app(); a.S.bets.device.member='p1'; a.b.data['bets/device'].member='p1';
  let release; a.b.gate=new Promise(resolve=>release=resolve);
  const first=a.A.betSelf(), second=a.A.betSelf();
  await new Promise(setImmediate);
  assert.equal(a.S.bets.device.tickets.length,0);
  assert.ok(!a.messages.some(m=>m.includes('単勝')));
  release(); await Promise.all([first,second]);
  assert.equal(a.b.data['bets/device'].tickets.length,1);
  assert.equal(a.S.ui.ticketPending,false);
});

test('two clients updating the same ledger preserve both entries',async()=>{
  const b=backend(), a=await app(b), other=await app(b);
  await Promise.all([
    a.mutateLedger(l=>l.entries.push({id:'first',amt:100})),
    other.mutateLedger(l=>l.entries.push({id:'second',amt:200})),
  ]);
  assert.equal(b.data['game/ledger'].entries.length,7);
  assert.ok(b.data['game/ledger'].entries.some(e=>e.id==='first'));
  assert.ok(b.data['game/ledger'].entries.some(e=>e.id==='second'));
  assert.ok(b.attempts>2,'A conflicting transaction should retry');
});

test('remote closure rejects a stale purchase and stale cancellation',async()=>{
  const a=await app(); a.b.data['game/state'].races[0].status='closed';
  assert.equal(await a.A.bet(),false);
  assert.equal(a.b.data['bets/device'].tickets.length,0);
  assert.match(a.messages.at(-1),/受付は終了/);
  assert.equal(await a.A.cancelT({id:'missing'}),false);
  assert.match(a.messages.at(-1),/取り消しできません/);
});

test('negative, zero, fractional, and infinite stakes are rejected',async()=>{
  for(const amt of [-100,0,1.5,Infinity,NaN,150]) {
    const a=await app(); a.S.ui.amt=amt;
    assert.equal(await a.A.bet(),false,`stake ${amt}`);
    assert.equal(a.b.data['bets/device'].tickets.length,0);
  }
});

test('latest server tickets are checked against balance even with a stale screen',async()=>{
  const a=await app();
  a.b.data['bets/device'].tickets.push({id:'remote',race:'r1',member:'p5',m:'win',sel:['p1'],amt:1000,t:Date.now()});
  assert.equal(await a.A.bet(),false);
  assert.equal(a.b.data['bets/device'].tickets.length,1);
  assert.match(a.messages.at(-1),/足りません/);
});

test('a failed cancellation keeps the ticket and does not announce success',async()=>{
  const a=await app(); await a.A.bet(); a.messages.length=0; offline(a);
  assert.equal(await a.A.cancelT({id:a.S.bets.device.tickets[0].id}),false);
  assert.equal(a.S.bets.device.tickets.length,1);
  assert.ok(!a.messages.includes('取り消しました'));
});

test('proxy bet failure retains the selection; runners cannot bet on other racers',async()=>{
  const a=await app(); a.S.ui.proxyMember='p5'; a.S.ui.psel=['p1']; offline(a);
  assert.equal(await a.A.pbet(),false);
  assert.deepEqual(a.S.ui.psel,['p1']);
  assert.equal(a.b.data['bets/proxy'],undefined);
  a.S.ui.proxyMember='p1'; a.S.ui.psel=['p2'];
  assert.equal(await a.A.pbet(),false);
  assert.match(a.messages.at(-1),/自分への単勝/);
});

test('result failure leaves both race and history unchanged and retains the entered order',async()=>{
  const a=await app(); closed(a); offline(a);
  const before=clone(a.b.data);
  assert.equal(await a.A.confirmResult(),false);
  assert.deepEqual(a.b.data,before);
  assert.equal(a.S.state.races[0].status,'closed');
  assert.deepEqual(a.S.ui.order,['p1','p2','p3']);
});

test('result and history commit together; failed undo keeps both, successful undo clears both',async()=>{
  const a=await app(); closed(a);
  assert.equal(await a.A.confirmResult(),true);
  assert.equal(a.b.commits,1);
  assert.equal(a.S.state.races[0].status,'done');
  assert.equal(a.S.history.races.length,1);
  assert.deepEqual(clone(a.S.history.races[0].order),['p1','p2','p3','p4']);
  offline(a);
  assert.equal(await a.A.undoResult(),false);
  assert.equal(a.S.state.races[0].status,'done');
  assert.equal(a.b.data['game/history'].races.length,1);
  assert.equal(await a.A.undoResult(),true);
  assert.equal(a.b.data['game/state'].races[0].status,'closed');
  assert.equal(a.b.data['game/history'].races.length,0);
});

test('double result confirmation cannot create duplicate history or re-settle a race',async()=>{
  const a=await app(); closed(a);
  const results=await Promise.all([a.A.confirmResult(),a.A.confirmResult()]);
  assert.deepEqual(results,[true,false]);
  assert.equal(a.b.data['game/history'].races.length,1);
  assert.equal(a.b.commits,1);
});

test('result cannot overwrite a race changed by another host',async()=>{
  const a=await app(); closed(a); a.b.data['game/state'].races[0].status='open';
  assert.equal(await a.A.confirmResult(),false);
  assert.equal(a.b.data['game/state'].races[0].status,'open');
  assert.equal(a.b.data['game/history'].races.length,0);
});

test('Firestore object key order does not cause false result conflicts',async()=>{
  const a=await app(); closed(a);
  a.b.data['game/state'].races[0]=Object.fromEntries(Object.entries(a.b.data['game/state'].races[0]).reverse());
  assert.equal(await a.A.confirmResult(),true);
});


test('double next-race action advances once instead of skipping a race',async()=>{
  const a=await app();
  const state=a.S.state;
  state.races[0].status='done';
  state.races.push({...clone(state.races[0]),id:'r2',no:2,status:'wait'}, {...clone(state.races[0]),id:'r3',no:3,status:'wait'});
  a.b.data['game/state']=clone(state);
  assert.deepEqual(await Promise.all([a.A.nextRace(),a.A.nextRace()]),[true,false]);
  assert.equal(a.b.data['game/state'].cur,1);
  assert.equal(a.b.data['game/state'].races[1].status,'open');
  assert.equal(a.b.data['game/state'].races[2].status,'wait');
});

test('stale host cannot close a different race',async()=>{
  const a=await app();
  a.b.data['game/state'].races[0].id='another-race';
  assert.equal(await a.A.closeNow(),false);
  assert.equal(a.b.data['game/state'].races[0].status,'open');
});

test('double finals creation creates one set of final races',async()=>{
  const a=await app(); closed(a); await a.A.confirmResult();
  assert.deepEqual(await Promise.all([a.A.makeFinals(),a.A.makeFinals()]),[true,false]);
  assert.equal(a.b.data['game/state'].races.filter(r=>r.type==='g1').length,1);
  assert.equal(a.b.data['game/state'].races.filter(r=>r.type==='dobe').length,1);
});

test('closing the final-chip table preserves all event data',async()=>{
  const a=await app(); a.S.state.ended=12345; a.b.data['game/state']=clone(a.S.state);
  const before=clone(a.b.data);
  a.A.endDismiss();
  assert.equal(a.S.ui.endDismissed,12345);
  assert.deepEqual(a.b.data,before);
  assert.equal(a.S.state.members.length,5);
  assert.equal(a.b.commits,0);
});

test('new-event reset requires confirmation; failed reset retains the event',async()=>{
  const a=await app(); a.S.state.ended=12345; a.b.data['game/state']=clone(a.S.state);
  assert.equal(await a.A.endClose(),false);
  a.S.ui.confirm='newday'; offline(a);
  assert.equal(await a.A.endClose(),false);
  assert.equal(a.S.state.members.length,5);
  assert.equal(await a.A.endClose(),true);
  assert.equal(a.S.state.members.length,0);
  assert.equal(a.S.state.ended,null);
  assert.equal(a.S.ui.adminPhase,'prep');
});

test('failed CSV export does not silently end the event',async()=>{
  const a=await app(); a.S.ui.confirm='end:save';
  a.context.claude.use=async()=>({save:async()=>{throw new Error('Download rejected');}});
  assert.equal(await a.A.endGame({s:'save'}),false);
  assert.equal(a.b.data['game/state'].ended,undefined);
  assert.equal(a.S.ui.confirm,'end:save');
  assert.equal(a.S.ui.ending,false);
  assert.match(a.messages.at(-1),/大会は終了していません/);
});


test('chip transfer failure retains amount and never announces a successful transfer',async()=>{
  const a=await app(); a.S.ui.form.send_p5='200'; offline(a);
  assert.equal(await a.A.send({id:'p5',sign:'1'}),false);
  assert.equal(a.S.ui.form.send_p5,'200');
  assert.equal(a.b.data['game/ledger'].entries.length,5);
  assert.ok(!a.messages.some(m=>m.includes('配りました')));
  assert.equal(await a.A.send({id:'p5',sign:'1'}),true);
  assert.equal(a.b.data['game/ledger'].entries.length,6);
  assert.equal(a.S.ui.form.send_p5,'');
});

test('double chip transfer submits once',async()=>{
  const a=await app(); a.S.ui.form.send_p5='200';
  const results=await Promise.all([a.A.send({id:'p5',sign:'1'}),a.A.send({id:'p5',sign:'1'})]);
  assert.deepEqual(results,[true,false]);
  assert.equal(a.b.data['game/ledger'].entries.length,6);
});

test('chip reduction uses fresh server ledger when the displayed balance is stale',async()=>{
  const a=await app();
  a.b.data['game/ledger'].entries.push({gameId:'test-game',member:'p5',amt:-900});
  a.S.ui.form.send_p5='200';
  assert.equal(await a.A.send({id:'p5',sign:'-1'}),false);
  assert.equal(a.b.data['game/ledger'].entries.length,6);
  assert.match(a.messages.at(-1),/残高を超える/);
});

test('settings failure retains unsaved form values',async()=>{
  const a=await app(); a.S.ui.form.rate_win='70'; offline(a);
  assert.equal(await a.A.saveSettings(),false);
  assert.equal(a.S.ui.form.rate_win,'70');
  assert.ok(!a.messages.includes('設定を保存しました'));
});

test('creating the schedule moves the host from setup to live control',async()=>{
  const a=await app();
  a.S.state.races=[]; a.S.state.cur=-1; a.b.data['game/state']=clone(a.S.state);
  a.S.ui.adminPhase='prep'; a.S.ui.raceCount=3;
  assert.equal(await a.A.makeSchedule(),true);
  assert.equal(a.S.ui.adminPhase,'live');
  assert.equal(a.b.data['game/state'].races.length,3);
  assert.equal(a.b.data['game/state'].races[0].status,'open');
});
