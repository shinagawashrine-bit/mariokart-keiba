"""Exercise real application DOM with a local Firestore double; block external traffic."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parent.parent


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
        page.add_init_script("localStorage.setItem('mk_device','real-player-device'); localStorage.setItem('mk_admin','keep-existing-role');")
        requests=[]
        page.on('request',lambda r: requests.append(r.url))
        page.goto(f'http://127.0.0.1:{server.server_port}/demo/characters/#bet')
        page.wait_for_function('S.ready')
        expect(page.locator('.rcard .character-kart')).to_have_count(4)
        page.locator('[data-act="pick"][data-id="p1"]').click()
        expect(page.locator('.rcard[data-id="p1"]')).to_have_class('rcard c0 sel')
        page.evaluate('window.scrollTo(0,0)')
        for card in page.locator('.rcard').all():
            box=card.bounding_box()
            assert box['y']+box['height']<=page.locator('.betbar').bounding_box()['y'], 'Card covered by purchase controls'
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
        print('PASS: independent character demo, single/exacta purchase, amount, cancellation, reset, narrow screen, and production storage isolation',flush=True)
        browser.close()

finally:
    server.shutdown()
    server.server_close()
    thread.join()
