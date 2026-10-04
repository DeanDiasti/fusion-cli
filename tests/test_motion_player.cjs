// Execute the real generated player's JavaScript with a minimal DOM and clock.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('fusion_addin/CadBot/tools/motion.py','utf8');
const template=source.match(/html='''([\s\S]*?)'''/)[1];
for(const mode of ['once','loop','ping-pong']){
  const html=template.replace('FRAMES',JSON.stringify(['f0','f1','f2'])).replace('FPS','2').replace('MODE',JSON.stringify(mode));
  const js=html.match(/<script>([\s\S]*?)<\/script>/)[1];
  const elements={frame:{},seek:{value:0},play:{textContent:'Pause'}};
  let tick,interval;
  vm.runInNewContext(js,{document:{getElementById:id=>elements[id]},setInterval:(fn,ms)=>{tick=fn;interval=ms;}});
  assert.equal(elements.frame.src,'f0');assert.equal(elements.seek.max,2);assert.equal(interval,500);
  const frames=[];for(let i=0;i<6;i++){tick();frames.push(elements.frame.src);}
  const expected=mode==='once'?['f1','f2','f2','f2','f2','f2']:mode==='loop'?['f1','f2','f0','f1','f2','f0']:['f1','f2','f1','f0','f1','f2'];
  assert.deepEqual(frames,expected);
  if(mode==='once'){assert.equal(elements.play.textContent,'Replay');elements.play.onclick();assert.equal(elements.frame.src,'f0');tick();assert.equal(elements.frame.src,'f1');}
  elements.play.onclick();const paused=elements.frame.src;tick();assert.equal(elements.frame.src,paused);
  elements.seek.value='1';elements.seek.oninput();assert.equal(elements.frame.src,'f1');
}
console.log('Motion player: once/replay, loop, ping-pong, pause and scrubbing passed.');
