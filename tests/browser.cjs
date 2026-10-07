const {chromium}=require('playwright');
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs');const path=require('node:path');const os=require('node:os');
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'clipa-browser-'));
const root=path.resolve(__dirname,'..');
const video=path.join(dir,'test.mp4');
let server,browser;
(async()=>{try{
const ff=spawnSync('ffmpeg',['-nostdin','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=320x240:rate=15','-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','4','-c:v','libx264','-c:a','aac',video]);if(ff.status!==0)throw Error(ff.stderr.toString());
server=spawn(path.join(root,'.venv/bin/python'),['-m','uvicorn','backend.app:app','--host','127.0.0.1','--port','8765','--no-access-log'],{cwd:root,env:{...process.env,CLIPA_DATA_DIR:dir,CLIPA_BASE_URL:'http://localhost:8765',CLIPA_PASSWORD:'',OPENAI_API_KEY:''},stdio:'pipe'});
let stderr='';server.stderr.on('data',d=>stderr+=d);
for(let i=0;i<50;i++){try{const response=await fetch('http://127.0.0.1:8765/api/config');if(response.ok)break}catch{}await new Promise(r=>setTimeout(r,100));if(i===49)throw Error('Server not ready: '+stderr)}
browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
const page=await browser.newPage({viewport:{width:1440,height:1080}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto('http://127.0.0.1:8765/');await page.locator('.account').first().waitFor();
if(await page.locator('.account').count()!==4)throw Error('Platform cards missing');
await page.locator('#file').setInputFiles(video);await page.waitForFunction(()=>document.querySelector('#status').textContent==='Vídeo pronto para analisar.');
const segments=[{start:0,end:2,text:'Uma boa história'},{start:2,end:4,text:'Uma ideia completa'}];
const clips=[{start:0,end:3,title:'História de teste',reason:'Trecho fictício para verificar a interface.'}];
// Mock only paid external speech analysis. Upload, rendering and downloads are real.
await page.route('**/api/analyze',async route=>route.fulfill({json:{job_id:'browser-analysis'}}));
await page.route('**/api/jobs/browser-analysis',async route=>route.fulfill({json:{status:'done',progress:'Análise de teste',result:{segments,clips}}}));
const seeded=spawnSync(path.join(root,'.venv/bin/python'),['-c',`import sqlite3,json; c=sqlite3.connect(${JSON.stringify(path.join(dir,'clipa.sqlite3'))}); c.execute('UPDATE videos SET transcript=?',(json.dumps(${JSON.stringify(segments)}),)); c.commit()`]);if(seeded.status!==0)throw Error(seeded.stderr.toString());
await page.locator('#settings2').click();await page.locator('#key').fill('sk-test-not-real');await page.locator('#savekey').click();await page.locator('#generate').click();await page.locator('.card video').waitFor();
await page.locator('#editcaptions').click();await page.locator('#captionrows textarea').first().fill('Legenda revisada no navegador');await page.locator('#savecaptions').click();
await page.locator('.card > button').click();await page.locator('.actions a').first().waitFor({timeout:20000});
const href=await page.locator('.actions a').first().getAttribute('href');const result=await page.request.get(new URL(href,'http://127.0.0.1:8765').href);if(!result.ok()||result.headers()['content-type']!=='video/mp4')throw Error('MP4 download failed');
const captionsHref=await page.locator('.actions a').nth(1).getAttribute('href');const captions=await page.request.get(new URL(captionsHref,'http://127.0.0.1:8765').href);if(!(await captions.text()).includes('Legenda revisada no navegador'))throw Error('Subtitle edit not applied');
await page.locator('.actions button').click();await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('Conecte uma conta oficial'));
await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));
await page.screenshot({path:path.join(root,'preview-desktop.png'),fullPage:true});
await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(root,'preview-mobile.png'),fullPage:true});
const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);if(overflow)throw Error('Mobile horizontal overflow');
if(errors.length)throw Error(errors.join('\n'));
console.log('Browser QA passed: upload, suggestions (mock AI), subtitle editing, real MP4 + audio render, downloads, unconfigured accounts, mobile layout.');
}finally{if(browser)await browser.close();if(server)server.kill('SIGTERM');fs.rmSync(dir,{recursive:true,force:true});}})().catch(e=>{console.error(e);process.exitCode=1});
