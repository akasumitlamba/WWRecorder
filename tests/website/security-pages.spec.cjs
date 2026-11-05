// Run: node tests/website/security-pages.spec.cjs. WWR_SITE_ROOT can select the public site root.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const site = path.resolve(process.env.WWR_SITE_ROOT || (fs.existsSync('Supporting/Website/site') ? 'Supporting/Website/site' : '.'));
const prefix = 'https://github.com/akasumitlamba/WWRecorder/releases/download/';
const release = (tag, options = {}) => ({tag_name:tag, published_at:'2026-01-01T00:00:00Z', prerelease:false, draft:false, assets:[{name:`WWRecorder_Setup_${tag.slice(1)}.exe`,browser_download_url:`${prefix}${tag}/WWRecorder_Setup_${tag.slice(1)}.exe`}], ...options});
const stable = release('v2.4');
const older = release('v2.3', {published_at:'2026-10-28T00:00:00Z'});
const preview = release('v99', {prerelease:true});
const specialPreview = release('v1.7.1', {prerelease:true});
const draft = release('v100', {draft:true});
const releases = [preview, specialPreview, draft, older, stable];
const results = [];
const server=http.createServer((req,res)=>{
 const requested=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
 const file=path.resolve(site,'.'+(requested==='/'?'/index.html':requested));
 if(!file.startsWith(site+path.sep)){res.writeHead(403).end();return;}
 fs.readFile(file,(error,data)=>{if(error){res.writeHead(404).end();return;}res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png'})[path.extname(file)]||'application/octet-stream');res.end(data);});
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const base=`http://127.0.0.1:${server.address().port}`;
 const browser=await chromium.launch({headless:true});
 try {
  const ctx=await browser.newContext({viewport:{width:1440,height:1000}});
  let list=releases, latest=stable, failLatest=false, failList=false;
  const downloads=[];
  await ctx.route('https://api.github.com/**',r=>{
   const isLatest=new URL(r.request().url()).pathname.endsWith('/latest');
   if(isLatest?failLatest:failList)return r.abort();
   return r.fulfill({json:isLatest?latest:list});
  });
  await ctx.route('https://fonts.**',r=>r.abort());
  await ctx.route('https://github.com/**',r=>{downloads.push(r.request().url());return r.abort();});
  const page=await ctx.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const go=async(query='')=>{downloads.length=0;await page.goto(base+'/download.html'+query,{waitUntil:'domcontentloaded'});};
  const selected=async(item)=>{await page.waitForFunction(url=>document.querySelector('[data-manual-download]').href===url,item.assets[0].browser_download_url);};
  const fallback=async()=>{await page.getByText('Open the latest stable release',{exact:true}).waitFor();assert.equal(await page.locator('[data-manual-download]').getAttribute('href'),'https://github.com/akasumitlamba/WWRecorder/releases/latest');await page.waitForTimeout(1100);assert.deepEqual(downloads,[]);};
  const check=async(name,fn)=>{await fn();results.push({name,status:'passed'});};
  await check('Default uses GitHub latest stable, ignoring newer previews and date ordering',async()=>{
   await go();await selected(stable);assert.equal(await page.locator('[data-version-select] option').count(),2);assert.match(await page.locator('[data-version-select] option:checked').innerText(),/latest stable/);await page.waitForTimeout(1100);assert.deepEqual(downloads,[stable.assets[0].browser_download_url]);
  });
  await check('No hardcoded release: changing the latest response changes the download',async()=>{
   latest=release('v8.9');await go();await selected(latest);assert.equal(await page.locator('[data-version-select] option').count(),3);latest=stable;
  });
  await check('Explicit older stable selection is respected',async()=>{await go('?version='+older.tag_name);await selected(older);});
  await check('Prerelease version query cannot select a preview',async()=>{await go('?version=v1.7.1');await selected(stable);});
  await check('Prerelease URL query cannot select a preview',async()=>{await go('?url='+encodeURIComponent(preview.assets[0].browser_download_url));await selected(stable);});
  await check('Untrusted URL query cannot replace the official stable installer',async()=>{await go('?url='+encodeURIComponent('https://example.invalid/fake.exe'));await selected(stable);});
  await check('Latest API failure offers dynamic stable fallback without auto-downloading',async()=>{failLatest=true;await go();await fallback();failLatest=false;});
  await check('Release list failure does not auto-download a preview or guess an older version',async()=>{failList=true;await go();await fallback();failList=false;});
  await check('Invalid prerelease latest metadata is rejected',async()=>{latest=preview;await go();await fallback();latest=stable;});
  await check('Missing latest installer never falls back automatically to an older installer',async()=>{latest=release('v8.9',{assets:[]});await go();await fallback();latest=stable;});
  await check('Version dropdown switches only to reviewed stable metadata',async()=>{await go();await selected(stable);await page.locator('[data-version-select]').selectOption(older.assets[0].browser_download_url);await selected(older);assert.match(await page.locator('[data-download-title]').innerText(),/Ready/);});
  await check('Installer fingerprint checker still distinguishes known and unknown files',async()=>{
   await page.goto(base+'/install-help.html');await page.locator('[data-hash-input]').fill('0d7e75e3b9723478117afed3f17b77f2fa05dfd5ab39e0e62eddc3d602eac7cd');await page.locator('[data-check-hash]').click();assert.match(await page.locator('[data-hash-result]').innerText(),/1.7.1/);await page.locator('[data-hash-input]').fill('a'.repeat(64));await page.locator('[data-check-hash]').click();assert.doesNotMatch(await page.locator('[data-hash-result]').innerText(),/Fingerprint matches/);
  });
  await check('Notice labels preview separately and dismisses across navigation',async()=>{
   await page.evaluate(()=>sessionStorage.clear());await page.goto(base+'/enterprise.html');await page.locator('.security-notice').waitFor();assert.match(await page.locator('.security-notice').innerText(),/preview/);assert.equal(await page.locator('.security-notice a[href="download.html?version=v1.7.1"]').count(),0);await page.getByRole('button',{name:'Dismiss security update notice'}).click();await page.goto(base+'/privacy-policy.html');assert.equal(await page.locator('.security-notice').count(),0);
  });
  await check('Phone layout and navigation remain usable',async()=>{
   await page.setViewportSize({width:375,height:812});await page.goto(base+'/download.html');await selected(stable);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.getByRole('button',{name:'Open navigation'}).click();assert.equal(await page.locator('.menu-toggle').getAttribute('aria-expanded'),'true');
  });
  await check('Blocked session storage does not break stable download selection',async()=>{
   await ctx.addInitScript(()=>Object.defineProperty(window,'sessionStorage',{get(){throw new Error('blocked')}}));await go();await selected(stable);
  });
  assert.deepEqual(errors,[]);
  if(process.env.WWR_WEBSITE_REPORT)fs.writeFileSync(process.env.WWR_WEBSITE_REPORT,JSON.stringify(results,null,2));
  console.log(`${results.length} browser checks passed`);
 } finally {await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
