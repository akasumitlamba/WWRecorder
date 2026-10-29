// Real browser checks: npm install --no-save playwright, then node this file.
// WWR_SITE_ROOT optionally selects the exported public tree; no app or network input required.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const site = path.resolve(process.env.WWR_SITE_ROOT || (fs.existsSync('Supporting/Website/site') ? 'Supporting/Website/site' : '.'));
const patched = 'https://github.com/akasumitlamba/WWRecorder/releases/download/v1.7.1/WWRecorder_Setup_1.7.1.0.exe';
const asset = name => ({name, browser_download_url:'https://github.com/akasumitlamba/WWRecorder/releases/download/v1.7.1/'+name});
const releases = [
 {tag_name:'v1.6',published_at:'2026-09-08T00:00:00Z',assets:[asset('WWRecorder_Setup_1.6.3.exe')]},
 {tag_name:'v1.7.1',prerelease:false,published_at:'2026-10-29T00:00:00Z',assets:[asset('WWRecorder_Setup_1.7.0.14.exe'),asset('WWRecorder_Setup_1.7.1.0.exe')]},
 {tag_name:'v9',prerelease:true,assets:[asset('Unreviewed.exe')]},
 {tag_name:'draft',draft:true,assets:[asset('Draft.exe')]}
];
const results=[];
const server=http.createServer((req,res)=>{
 const requested=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
 const file=path.resolve(site,'.'+(requested==='/'?'/index.html':requested));
 if(!file.startsWith(site+path.sep)){res.writeHead(403).end();return;}
 fs.readFile(file,(error,data)=>{
  if(error){res.writeHead(404).end();return;}
  res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png'})[path.extname(file)]||'application/octet-stream');res.end(data);
 });
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const base=`http://127.0.0.1:${server.address().port}`;
 const browser=await chromium.launch({headless:true});
 try {
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.route('https://api.github.com/**',r=>r.fulfill({json:releases}));
  await context.route('https://fonts.**',r=>r.abort());
  await context.route('https://github.com/**',r=>r.abort());
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const check=async(name,fn)=>{await fn();results.push({name,status:'passed'});};
  await check('Notice is accessible, visible and dismisses across page navigation',async()=>{
   await page.goto(base+'/enterprise.html');await page.locator('.security-notice').waitFor();
   assert.equal(await page.locator('.security-notice').getAttribute('role'),'status');
   assert.match(await page.locator('.security-notice').innerText(),/FFmpeg security fix/);
   await page.screenshot({path:process.env.WWR_WEBSITE_SCREENSHOT || 'work/enterprise-desktop.png',fullPage:true});
   await page.getByRole('button',{name:'Dismiss security update notice'}).click();
   assert.equal(await page.locator('.security-notice').count(),0);
   await page.goto(base+'/privacy-policy.html');assert.equal(await page.locator('.security-notice').count(),0);
  });
  await check('Policy key and values, disclosure and Store trust are visible',async()=>{
   await page.goto(base+'/enterprise.html');
   for(const text of ['DisableKeycast','DisableAutomaticClipboard','CVE-2026-8461','9.0.2','9.0.1','direct-download EXE is unsigned'])assert.ok((await page.locator('main').innerText()).includes(text));
   assert.ok(await page.locator('footer a[href="enterprise.html"]').count());
   assert.ok(await page.locator('#site-nav a[href="enterprise.html"]').count());
  });
  await check('Exact patched asset wins over old release assets, drafts and unrelated previews',async()=>{
   await page.goto(base+'/download.html');
   await page.waitForFunction(expected=>document.querySelector('[data-manual-download]').href===expected,patched);
   assert.equal(await page.locator('[data-version-select] option').count(),2);
   assert.match(await page.locator('[data-version-select] option:checked').innerText(),/patched 1.7.1/);
  });
  await check('Offline lookup offers the patched release instead of older stable',async()=>{
   await context.route('https://api.github.com/**',r=>r.abort());
   await page.goto(base+'/download.html');await page.getByText('Open the patched release release',{exact:true}).waitFor();
   assert.equal(await page.locator('[data-manual-download]').getAttribute('href'),'https://github.com/akasumitlamba/WWRecorder/releases/tag/v1.7.1');
  });
  await check('Missing patched metadata never silently starts an older build',async()=>{
   await context.route('https://api.github.com/**',r=>r.fulfill({json:[releases[0]]}));
   await page.goto(base+'/download.html');await page.getByText('Open the patched release release',{exact:true}).waitFor();
   assert.equal(await page.locator('[data-manual-download]').getAttribute('href'),'https://github.com/akasumitlamba/WWRecorder/releases/tag/v1.7.1');
  });
  await check('Phone layout has no horizontal overflow; notice and menu work',async()=>{
   await page.setViewportSize({width:375,height:812});
   await page.evaluate(()=>sessionStorage.clear());
   await page.goto(base+'/enterprise.html');
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   const box=await page.locator('.security-notice').boundingBox();assert.ok(box.x>=0&&box.x+box.width<=375);
   await page.getByRole('button',{name:'Dismiss security update notice'}).click();
   await page.getByRole('button',{name:'Open navigation'}).click();
   assert.equal(await page.locator('.menu-toggle').getAttribute('aria-expanded'),'true');
   await page.locator('#site-nav a[href="enterprise.html"]').click();
   await page.screenshot({path:process.env.WWR_WEBSITE_MOBILE_SCREENSHOT || 'work/enterprise-mobile.png',fullPage:true});
  });
  await check('Installer fingerprint feedback distinguishes patched, old and unknown files',async()=>{
   await page.goto(base+'/install-help.html');
   await page.locator('[data-hash-input]').fill('1b87b1cd6aabee45c6fc4d08dad9a82660020366a308742a8a9d519d8a260fbc');
   await page.locator('[data-check-hash]').click();
   assert.match(await page.locator('[data-hash-result]').innerText(),/1.7.1/);
   await page.locator('[data-hash-input]').fill('ec30b53e4f0ce2ac57ffac66d3f9c90340b4dca5c7ca9e6391926e6a82720eb9');
   await page.locator('[data-check-hash]').click();assert.match(await page.locator('[data-hash-result]').innerText(),/older version does not contain/);
   await page.locator('[data-hash-input]').fill('0'.repeat(64));await page.locator('[data-check-hash]').click();
   assert.match(await page.locator('[data-hash-result]').innerText(),/No match/);
  });
  await check('Blocked browser storage never prevents notice dismissal',async()=>{
   const isolated=await browser.newContext();
   await isolated.route('https://**',r=>r.abort());
   await isolated.addInitScript(()=>Object.defineProperty(window,'sessionStorage',{get(){throw new Error('Storage unavailable');}}));
   const tab=await isolated.newPage();await tab.goto(base+'/enterprise.html');
   await tab.getByRole('button',{name:'Dismiss security update notice'}).click();assert.equal(await tab.locator('.security-notice').count(),0);
   await isolated.close();
  });
  assert.deepEqual(errors,[]);await context.close();
 }finally{await browser.close();server.close();}
 const report=process.env.WWR_WEBSITE_REPORT||'work/website-test-report.json';fs.mkdirSync(path.dirname(report),{recursive:true});fs.writeFileSync(report,JSON.stringify({passed:results.length,failed:0,results},null,2));console.log(`${results.length} browser checks passed`);
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
