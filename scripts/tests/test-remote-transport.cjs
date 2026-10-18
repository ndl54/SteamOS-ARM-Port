const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../../dualscreen-overlay/usr/lib/steamos-arm/bottom-screen/qml/Ui.qml'),'utf8');
function fn(name) {
  const start=source.indexOf('    function '+name+'('), body=source.indexOf('{',start);
  let depth=1,end=body+1;
  for(;depth;end++) {if(source[end]==='{')depth++;else if(source[end]==='}')depth--;}
  return source.slice(start,end);
}
function setup() {
 const requests=[];
 const c={remoteSession:'',remoteSequence:0,remoteOpening:false,remotePending:[],remoteEvents:[],remoteBusy:false,
 request(method,path,body,done){requests.push({method,path,body,done});}};
 vm.createContext(c);vm.runInContext(fn('drainRemote')+'\n'+fn('send'),c);
 return {c,requests};
}
test('one handshake and ordered down/up/release despite rapid fire',()=>{
 const {c,requests:r}=setup();
 c.send('/remote/click',{state:'down'});c.send('/remote/click',{state:'up'});c.send('/remote/letgo',{});
 assert.equal(r.length,1);assert.equal(r[0].path,'/remote/open');
 r.shift().done({session:'token'});
 assert.equal(r.length,1);assert.equal(r[0].body.sequence,1);assert.equal(r[0].body.state,'down');
 c.send('/remote/keepalive',{});assert.equal(r.length,1);
 r.shift().done({ok:true});assert.equal(r[0].body.sequence,2);assert.equal(r[0].body.state,'up');
 r.shift().done({ok:true});assert.equal(r[0].path,'/remote/letgo');assert.equal(r[0].body.sequence,3);
 r.shift().done({ok:true});assert.equal(c.remoteBusy,false);
});
test('failed acknowledgement never replays a stale down under a new session',()=>{
 const {c,requests:r}=setup();c.send('/remote/click',{state:'down'});r.shift().done({session:'old'});
 c.send('/remote/click',{state:'up'});r.shift().done(null);
 assert.equal(c.remoteSession,'');assert.equal(c.remoteEvents.length,0);assert.equal(r.length,0);
 c.send('/remote/move',{dx:2});r.shift().done({session:'new'});
 assert.equal(r[0].path,'/remote/move');assert.equal(r[0].body.sequence,1);
});
