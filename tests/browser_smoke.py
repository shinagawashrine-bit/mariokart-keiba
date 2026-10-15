"""Exercise real application DOM with a local Firestore double; block external traffic."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
from threading import Thread
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent


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
        page.add_init_script("localStorage.setItem('mk_device','device');")
        fake_sdk = (ROOT/'tests/fake-firestore.js').read_text() + '''
window.testBackend=createTestFirestore();
window.firebase={apps:[{}],firestore:()=>testBackend.firestore};
'''

        def route_request(route):
            url = urlparse(route.request.url)
            if url.path == '/config.js':
                route.fulfill(content_type='application/javascript', body="window.MK_CONFIG={firebase:{apiKey:'local-test'}};")
            elif url.hostname == 'www.gstatic.com' and url.path.endswith('firebase-app-compat.js'):
                route.fulfill(content_type='application/javascript', body=fake_sdk)
            elif url.hostname == '127.0.0.1':
                route.continue_()
            else:
                route.fulfill(content_type='application/javascript', body='')

        page.route('**/*', route_request)
        print('Opening local application',flush=True)
        page.goto(f'http://127.0.0.1:{server.server_port}/#bet')
        print('Waiting for application initialization',flush=True)
        page.wait_for_function('S.ready')
        print('Application initialized',flush=True)
        page.locator('[data-act="pick"][data-id="p1"]').click()
        # Rejected writes must retain the chosen ticket and the displayed balance.
        page.evaluate("testBackend.fail=Object.assign(new Error('Test denial'),{code:'permission-denied'})")
        page.locator('[data-act="bet"]').click()
        expect(page.locator('#toast')).to_contain_text('権限')
        assert page.evaluate('S.bets.device.tickets.length') == 0
        assert page.evaluate('S.ui.sel.join()') == 'p1'
        expect(page.locator('.me .bal')).to_contain_text('1000')
        print('PASS: failed write retains selection and displayed balance')

        # Hold acknowledgment while testing the real disabled state.
        page.evaluate('() => {testBackend.gate=new Promise(resolve=>window.releaseWrite=resolve);}')
        page.locator('[data-act="bet"]').click()
        expect(page.locator('[data-act="bet"]')).to_be_disabled()
        assert page.evaluate('S.bets.device.tickets.length') == 0
        page.evaluate('releaseWrite()')
        expect(page.locator('#toast')).to_contain_text('賭けました')
        assert page.evaluate('S.bets.device.tickets.length') == 1
        expect(page.locator('.me .bal')).to_contain_text('900')
        print('PASS: pending button disabled; success and balance update after commit')

        page.locator('[data-act="cancelT"]').click()
        expect(page.locator('#toast')).to_contain_text('取り消しました')
        expect(page.locator('.me .bal')).to_contain_text('1000')
        assert page.evaluate('S.bets.device.tickets.length') == 0
        print('PASS: cancellation restores balance after commit')

        # Perform result confirmation and reversal through the admin controls.
        page.evaluate('''() => {
          S.isOwner=true;
          testBackend.data['game/state'].races[0].status='closed';
          testBackend.data['game/state'].races[0].closeAt=Date.now();
          testBackend.notify(); location.hash='admin';
        }''')
        for phase in ('prep','finish','live'):
            page.locator(f'[data-act="adminPhase"][data-phase="{phase}"]').click()
            expect(page.locator(f'.admin-phases button[data-phase="{phase}"]')).to_have_attribute('aria-current','page')
        assert page.locator('[data-act="makeSchedule"]').count()==0
        heading=page.locator('.admin .panel > h2').filter(has_text='出走表').first
        heading.focus(); heading.press('Enter')
        expect(heading).to_have_attribute('aria-expanded','false')
        heading.press('Space')
        expect(heading).to_have_attribute('aria-expanded','true')
        print('PASS: admin phase navigation and keyboard-accessible collapsible sections')
        for member in ('p1', 'p2', 'p3'):
            page.locator(f'[data-act="orderPick"][data-id="{member}"]').click()
        page.locator('[data-act="confirmResult"]').click()
        page.wait_for_function("S.state.races[0].status==='done' && S.history.races.length===1")
        page.locator('[data-act="undoResult"]').click()
        page.wait_for_function("S.state.races[0].status==='closed' && S.history.races.length===0")
        print('PASS: real admin controls commit and reverse result/history together')

        # Closing the end-of-day table must never reset the event.
        page.evaluate("testBackend.data['game/state'].ended=12345; testBackend.notify();")
        page.locator('[data-act="endDismiss"]').click()
        assert page.evaluate('S.state.members.length')==5
        assert page.evaluate("testBackend.data['game/state'].ended")==12345
        expect(page.locator('.endpop')).to_have_count(0)
        print('PASS: closing final table preserves event data')

        for route in ('bet', 'board', 'stats'):
            page.evaluate('(route)=>location.hash=route', route)
            page.wait_for_timeout(100)
            assert len(page.locator('#app').inner_text()) > 40
        assert not errors, errors
        print('PASS: mobile/admin/board/stats render without JavaScript errors')
        if os.environ.get('KEIBA_SCREENSHOT_DIR'):
            target=Path(os.environ['KEIBA_SCREENSHOT_DIR']); target.mkdir(parents=True,exist_ok=True)
            page.set_viewport_size({'width':1440,'height':1000})
            page.evaluate('''() => {
              clearTimeout(toast._t); document.getElementById('toast').innerHTML='';
              const b=createTestFirestore(), names=['たくみ','ゆう','はる','けん','さき','あおい','りょう','みな'];
              const state=b.data['game/state'];
              state.members=names.map((name,i)=>({id:'p'+(i+1),name}));
              state.round=1;
              state.races=Array.from({length:6},(_,i)=>({id:'r'+(i+1),no:i+1,round:1,type:'prelim',runners:['p1','p2','p3','p4'],status:i<2?'done':i===2?'countdown':'wait',closeAt:i===2?Date.now()+45000:null,settle:null}));
              state.cur=2;
              b.data['game/ledger'].entries=state.members.map(m=>({member:m.id,gameId:state.gameId,amt:1000,t:Date.now()-60000}));
              b.data['bets/device']={member:'p5',tickets:[{id:'t1',race:'r3',member:'p5',m:'win',sel:['p1'],amt:300,t:Date.now()-1000}]};
              b.data['bets/proxy']={tickets:[{id:'t2',race:'r3',member:'p6',m:'ex',sel:['p3','p1'],amt:500,t:Date.now()-1000}]};
              Object.assign(testBackend.data,b.data);
              testBackend.notify();
              S.ui.adminPhase='live'; S.ui.fold={}; S.ui.foldH={}; S.ui.endDismissed=null;
              location.hash='admin'; render();
            }''')
            page.evaluate('window.scrollTo(0,0)')
            expect(page.locator('.admin > .topnav .logo')).to_be_visible()
            expect(page.locator('.admin-phases button')).to_have_count(3)
            assert page.locator('.admin-shell, .admin-metrics').count()==0
            assert page.locator('.admin .timer').evaluate('(el)=>getComputedStyle(el).backgroundColor')=='rgb(24, 24, 29)'
            page.screenshot(path=str(target/'admin-live.png'),full_page=True)
            page.evaluate("testBackend.data['game/state'].races[2].status='closed'; testBackend.notify();")
            for member in ('p1','p3','p2'):
                page.locator(f'[data-act="orderPick"][data-id="{member}"]').click()
            page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=str(target/'admin-results.png'),full_page=True)
            page.locator('.admin-phases button[data-phase="prep"]').click()
            page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=str(target/'admin-prep.png'),full_page=True)
            page.locator('.admin-phases button[data-phase="live"]').click()
            page.set_viewport_size({'width':390,'height':844})
            page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=str(target/'admin-mobile.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Admin mobile overflow'
            assert not errors, errors
            print('PASS: desktop and mobile admin screenshots captured')
        browser.close()
finally:
    server.shutdown()
    server.server_close()
    thread.join()
