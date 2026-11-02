"""Exercise real application DOM with a local Firestore double; block external traffic."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parent.parent
for shot in ('phone-tickets-unified.png','phone-driver-unified.png','phone-stats-unified.png'):
    (Path('/tmp')/shot).unlink(missing_ok=True)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        page.set_default_timeout(10000)
        page.set_default_navigation_timeout(10000)
        errors = []
        page.on('pageerror', lambda e: (errors.append(str(e)), print('PAGE ERROR:',e,flush=True)))
        def assert_full_character_images():
            # Components may re-render between protocol calls: measure live SVGs atomically.
            page.wait_for_function("""()=>{
              const graphics=Array.from(document.querySelectorAll('.character-kart'));
              return graphics.length>0&&graphics.every(el=>{
                if(el.getAttribute('preserveAspectRatio')!=='xMidYMid meet') return false;
                const v=el.viewBox.baseVal,b=el.getBoundingClientRect(),m=el.getScreenCTM();
                if(!m||!b.width||!b.height) return false;
                const a=new DOMPoint(v.x,v.y).matrixTransform(m);
                const z=new DOMPoint(v.x+v.width,v.y+v.height).matrixTransform(m);
                return a.x>=b.left-1&&a.y>=b.top-1&&z.x<=b.right+1&&z.y<=b.bottom+1;
              });
            }""")

        page.add_init_script("localStorage.setItem('mk_device','real-player-device'); localStorage.setItem('mk_admin','keep-existing-role');")
        requests=[]
        page.on('request',lambda r: requests.append(r.url))
        page.goto(f'http://127.0.0.1:{server.server_port}/demo/characters/#bet')
        page.wait_for_function('S.ready')
        expect(page.locator('.rcard .character-kart')).to_have_count(4)
        expect(page.locator('.rcard .card-ai.pending')).to_have_count(4)
        page.locator('[data-act="pick"][data-id="p1"]').click()
        expect(page.locator('.rcard[data-id="p1"]')).to_have_class('rcard c0 sel')
        page.evaluate('window.scrollTo(0,0)')
        # Read the layout in one browser task so a re-render cannot detach a node mid-check.
        assert page.evaluate("""()=>{
            const bar=document.querySelector('.betbar').getBoundingClientRect();
            return Array.from(document.querySelectorAll('.rcard')).every(card=>card.getBoundingClientRect().bottom<=bar.top);
        }"""), 'Card covered by purchase controls'
        # Illustrations should dominate the card, rather than remain 60px icons.
        for image in page.locator('.rcard .kwrap').all():
            assert image.bounding_box()['height']>=105, 'Character image is too small'
        assert_full_character_images()
        page.screenshot(path='/tmp/character-demo-screen.png')
        page.locator('[data-act="bet"]').click()
        expect(page.locator('#toast')).to_contain_text('賭けました')
        assert page.evaluate('S.bets.device.tickets.length')==1
        expect(page.locator('.me .bal')).to_contain_text('900')
        page.locator('[data-act="cancelT"]').click()
        page.wait_for_function('S.bets.device.tickets.length===0')
        expect(page.locator('.me .bal')).to_contain_text('1000')
        page.set_viewport_size({'width':360,'height':800})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors,errors
        # Reloading the independent demo never changes the live app's local storage.
        assert page.evaluate("localStorage.getItem('mk_device')")=='real-player-device'
        assert page.evaluate("localStorage.getItem('mk_admin')")=='keep-existing-role'
        assert page.evaluate("S.state.races[0].status")=='open'
        page.locator('[data-act="tab"][data-m="ex"]').click()
        page.locator('[data-act="pick"][data-id="p3"]').click()
        page.locator('[data-act="pick"][data-id="p1"]').click()
        page.locator('[data-act="amt"][data-d="100"]').click()
        expect(page.locator('#amtInput')).to_have_value('200')
        page.locator('[data-act="bet"]').click()
        page.wait_for_function('S.bets.device.tickets.length===1')
        assert page.evaluate('S.bets.device.tickets[0].m')=='ex'
        assert page.evaluate('S.bets.device.tickets[0].amt')==200
        page.locator('[data-demo-reset]').click()
        page.wait_for_function('S.ready')
        assert page.evaluate('S.bets.device.tickets.length')==0
        expect(page.locator('.me .bal')).to_contain_text('1000')
        assert page.evaluate("localStorage.getItem('mk_device')")=='real-player-device'
        assert page.evaluate("localStorage.getItem('mk_admin')")=='keep-existing-role'
        assert all(urlparse(url).hostname=='127.0.0.1' or url.startswith('data:') for url in requests), requests
        assert not errors,errors
        print('PASS: independent demo purchase, cancellation, reset, storage isolation and uncropped artwork',flush=True)
        # Exercise the adopted artwork in the real app with only Firebase replaced.
        sdk=(ROOT/'tests/fake-firestore.js').read_text()+'''
window.testBackend=createTestFirestore();
const labels=['たくみ','ゆう','はる','けん','さき'];
testBackend.data['game/state'].members.forEach((m,i)=>m.name=labels[i]);
testBackend.data['bets/real-player-device']=testBackend.data['bets/device'];
window.firebase={apps:[{}],firestore:()=>testBackend.firestore};
'''
        def app_route(route):
            u=urlparse(route.request.url)
            if u.path=='/config.js':
                route.fulfill(content_type='application/javascript',body="window.MK_CONFIG={firebase:{apiKey:'local-test'}};")
            elif u.path.endswith('firebase-app-compat.js'):
                route.fulfill(content_type='application/javascript',body=sdk)
            elif u.hostname=='127.0.0.1': route.continue_()
            else: route.fulfill(content_type='application/javascript',body='')
        page.route('**/*',app_route)
        page.set_viewport_size({'width':390,'height':844})
        page.goto(f'http://127.0.0.1:{server.server_port}/#bet')
        page.wait_for_function('S.ready')
        expect(page.locator('.character-phone .rcard .character-kart')).to_have_count(4)
        page.locator('[data-act="pick"][data-id="p1"]').click()
        assert_full_character_images()
        # Read the layout in one browser task so a re-render cannot detach a node mid-check.
        assert page.evaluate("""()=>{
            const bar=document.querySelector('.betbar').getBoundingClientRect();
            return Array.from(document.querySelectorAll('.rcard')).every(card=>card.getBoundingClientRect().bottom<=bar.top);
        }"""), 'Card covered by purchase controls'
        expect(page.locator('.rcard .card-ai.pending')).to_have_count(4)
        assert page.locator('.card-odds-value').first.evaluate('(el)=>parseFloat(getComputedStyle(el).fontSize)')>=38
        page.screenshot(path='/tmp/character-app-no-crop.png')
        # Rankings need actual historical starts and must exclude this race's result.
        page.evaluate("""()=>{
          testBackend.data['game/history'].races=[
            {rid:'old-race',gid:'previous-game',t:Date.now()-86400000,type:'prelim',order:['p3','p1','p2','p4'],pl:{}},
            {rid:'r1',gid:'test-game',t:Date.now(),type:'prelim',order:['p4','p2','p1','p3'],pl:{}}
          ];
          testBackend.notify();
        }""")
        expect(page.locator('.rcard[data-id="p3"] .card-ai')).to_have_text('AI ◎')
        expect(page.locator('.rcard[data-id="p1"] .card-ai')).to_have_text('AI ○')
        expect(page.locator('.rcard[data-id="p2"] .card-ai')).to_have_text('AI ▲')
        expect(page.locator('.rcard[data-id="p4"] .card-ai')).to_have_text('AI —')
        colors=page.locator('.card-odds-value').evaluate_all('(els)=>els.map(el=>getComputedStyle(el).color)')
        assert colors==['rgb(255, 220, 53)','rgb(255, 255, 255)','rgb(255, 255, 255)','rgb(255, 255, 255)'], colors
        page.screenshot(path='/tmp/character-app-ai.png')
        page.locator('[data-act="bet"]').click()
        page.wait_for_function("S.bets['real-player-device'].tickets.length===1")
        expect(page.locator('.me .bal')).to_contain_text('900')
        assert page.evaluate("()=>document.querySelector('.toast').getBoundingClientRect().bottom<=document.querySelector('.betbar').getBoundingClientRect().top"), 'Notification covers purchase controls'
        expect(page.locator('.mybox-live > h2')).to_contain_text('あなたの馬券')
        expect(page.locator('.mybox-live > h2')).to_contain_text('合計 100枚')
        page.locator('[data-act="tab"][data-m="ex"]').click()
        expect(page.locator('[data-act="tab"][data-m="ex"]')).to_have_attribute('aria-pressed','true')
        page.locator('.poi').first.click()
        expect(page.locator('.poi[aria-pressed="true"]')).to_have_count(1)
        page.locator('[data-act="mark"][data-k="h"][data-id="p2"]').click()
        expect(page.locator('[data-act="mark"][data-k="h"][data-id="p2"]')).to_have_attribute('aria-pressed','true')
        page.evaluate("""()=>{
            clearTimeout(toast._t); document.getElementById('toast').innerHTML='';
            const rect=document.querySelector('.mybox-live').getBoundingClientRect();
            const panel=document.querySelector('.betbar').getBoundingClientRect();
            window.scrollBy(0,Math.max(0,rect.bottom-panel.top+16));
        }""")
        page.screenshot(path='/tmp/phone-tickets-unified.png')
        for width in (360,414):
            page.set_viewport_size({'width':width,'height':844})
            assert_full_character_images()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.evaluate("location.hash='board'")
        expect(page.locator('.board')).to_be_visible()
        assert page.locator('.character-kart').count()==0
        assert not errors,errors
        page.set_viewport_size({'width':390,'height':844})
        page.evaluate("testBackend.data['bets/real-player-device'].member='p1'; testBackend.notify(); location.hash='bet'")
        expect(page.locator('.cheer .character-kart')).to_be_visible()
        assert_full_character_images()
        expect(page.locator('.self-odds')).to_contain_text('倍')
        page.get_by_role('button',name='100枚増やす',exact=True).click()
        expect(page.locator('#amtInput')).to_have_value('200')
        page.locator('.selfbet').scroll_into_view_if_needed()
        page.screenshot(path='/tmp/phone-driver-unified.png',full_page=True)
        page.locator('[data-act="btab"][data-t="stats"]').click()
        expect(page.locator('[data-act="btab"][data-t="stats"]')).to_have_attribute('aria-current','page')
        expect(page.locator('.mystats')).to_be_visible()
        page.screenshot(path='/tmp/phone-stats-unified.png',full_page=True)
        print('PASS: actual app purchase, 360/390/414px containment, driver artwork, and unchanged board',flush=True)
        browser.close()

finally:
    server.shutdown()
    server.server_close()
    thread.join()
