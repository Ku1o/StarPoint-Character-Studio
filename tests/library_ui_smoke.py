"""Exercise installed official templates and real audio in headless Edge."""
import argparse
import json
from pathlib import Path
import sys
import threading
import time
import os
import socket
import subprocess
import urllib.request
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import create_server


def wait_for(page, expression, *, arg=None, timeout=30000):
    deadline=time.monotonic()+timeout/1000
    while time.monotonic()<deadline:
        if page.evaluate(expression,arg):return
        time.sleep(.05)
    raise AssertionError('Timed out: '+expression)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    server = worker = process = None
    if args.exe:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
        env["PATH"] = os.environ["SystemRoot"] + "\\System32;" + os.environ["SystemRoot"]
        process = subprocess.Popen([str(args.exe.resolve()), "--port", str(port), "--no-open", "--projects", str(output / "projects"), "--templates", str(args.library.resolve())], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        server = create_server(output / "projects", templates=args.library)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        port = server.server_port
    root = f"http://127.0.0.1:{port}"
    errors = []
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(root + "/api/session", timeout=1) as response:
                    session = json.load(response)
                break
            except OSError:
                if process and process.poll() is not None:
                    raise AssertionError("Distributed EXE exited before startup")
                time.sleep(.1)
        else:
            raise AssertionError("Studio did not start")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script("window.__audioStarted=[];window.__audioFetched=[];const fetchOriginal=window.fetch;window.fetch=function(url,...args){window.__audioFetched.push(String(url));return fetchOriginal.call(this,url,...args);};const old=AudioBufferSourceNode.prototype.start;AudioBufferSourceNode.prototype.start=function(when,...args){window.__audioStarted.push({when,time:this.context.currentTime,played:this.context.state==='running',duration:this.buffer?.duration});return old.call(this,when,...args);};")
            page.add_init_script("window.__loopStarted=[];window.__audioStopped=[];const start=AudioBufferSourceNode.prototype.start,stop=AudioBufferSourceNode.prototype.stop;AudioBufferSourceNode.prototype.start=function(when,...args){window.__loopStarted.push({when,loop:this.loop});return start.call(this,when,...args);};AudioBufferSourceNode.prototype.stop=function(when,...args){window.__audioStopped.push(when);return stop.call(this,when,...args);};")
            page.goto(root)
            page.locator("#import-template").click()
            page.locator("#template-more").click()
            assert page.locator("[data-template]").count() == 160
            page.locator("#template-search").fill("white_tiger")
            page.screenshot(path=str(output / "01-template-library.png"), full_page=True)
            page.locator('[data-template="10"]').click()
            page.locator("#template-create").click()
            page.locator("#compiled-preview").wait_for(timeout=60000)
            page.evaluate("async()=>{await preloadPreview();draw();}")
            assert page.evaluate("current().clips.every(c=>S.p.assets[c.asset].width>1)"), "Official idle must not gain an invented blank frame"
            bounds_report = page.evaluate("""()=>{const result=[];for(const a of S.p.animations){const b=PreviewLayout.animation(PreviewLayout.empty(),a,S.p.assets);for(const [w,h] of [[280,300],[720,420]]){const v=PreviewLayout.fit(b,w,h);if(v.x+b.minX*v.scale<31.9||v.x+b.maxX*v.scale>w-31.9||v.y+b.minY*v.scale<31.9||v.y+b.maxY*v.scale>h-31.9)throw Error('clipped '+a.name);}result.push({name:a.name,frames:duration(a),bounds:b});}return result;}""")
            # Real browser decoding is deliberately held; the visual clock must wait.
            page.evaluate("()=>{window.__originalDecode=HTMLImageElement.prototype.decode;HTMLImageElement.prototype.decode=async function(){await new Promise(r=>window.__releaseDecode=r);return window.__originalDecode.call(this);};}")
            page.locator('#play').click()
            assert page.evaluate("S.audioLoading&&!S.playing&&S.tick===0")
            page.evaluate("HTMLImageElement.prototype.decode=window.__originalDecode;window.__releaseDecode();")
            wait_for(page,"S.playing")
            page.locator('#play').click()
            page.screenshot(path=str(output / '02a-complete-idle.png'),full_page=True)
            assert page.locator('[aria-label="素材制作要求"]').count() == 1
            assert "PNG" in page.locator(".requirements").inner_text()
            page.locator(".requirements summary").first.click()
            assert "1022" in page.locator(".requirements").inner_text()
            page.screenshot(path=str(output / "02-pixel-requirements.png"), full_page=True)
            page.locator('[data-page="effects"]').click()
            assert page.locator(".sound-event").count() == 12
            before = page.evaluate("window.__audioStarted.length")
            page.locator("#play").click()
            page.wait_for_timeout(370)
            wait_for(page, "n=>window.__audioStarted.slice(n,n+2).length===2 && window.__audioStarted.slice(n,n+2).every(a=>a.played||a.error)", arg=before, timeout=10000)
            started = page.evaluate("window.__audioStarted.slice(" + str(before) + ")")
            assert len(started) >= 2, started
            assert started[0].get('played') and started[1].get('played'), started
            delta = (started[1]["when"] - started[0]["when"])*1000
            assert 140 < delta < 400, delta
            page.locator("#play").click()
            assert not page.locator("#toast.error:visible").count()
            page.screenshot(path=str(output / "03-effect-sounds.png"), full_page=True)
            page.locator('[data-event-start]').first.fill("4")
            page.locator('[data-event-start]').first.dispatch_event("change")
            page.locator("#compiled-preview").click()
            page.locator("#readback-play").wait_for()
            before = page.evaluate("window.__audioStarted.length")
            page.locator("#readback-play").click()
            page.wait_for_timeout(370)
            wait_for(page, "n=>window.__audioStarted.slice(n,n+2).length===2 && window.__audioStarted.slice(n,n+2).every(a=>a.played||a.error)", arg=before, timeout=10000)
            compiled = page.evaluate("window.__audioStarted.slice(" + str(before) + ")")
            assert len(compiled) >= 2 and page.evaluate("window.__audioFetched.some(u=>u==='/api/compiled-preview')")
            assert compiled[0].get('played') and compiled[1].get('played'), [{k:v for k,v in item.items() if k!='src'} for item in compiled]
            assert abs((compiled[1]['when']-compiled[0]['when'])*60-13)<.001, compiled[:2]
            page.locator(".modal-close").click()
            page.locator('[data-page="voices"]').click()
            page.locator("#audio-more").click()
            assert page.locator(".audio-row").count() == 200
            page.locator("#audio-filter").select_option("skill_voice")
            assert page.locator(".audio-row").count() > 0
            audio = page.locator("audio").first
            audio.evaluate("a=>a.load()")
            wait_for(page, "Number.isFinite(document.querySelector('#audio-rows audio').duration)")
            page.screenshot(path=str(output / "04-character-voices.png"), full_page=True)
            page.locator('[data-audio-tab="sounds"]').click()
            assert page.locator(".audio-row").count() == 2
            page.locator('[data-audio-track]').first.click()
            manual_track_ids = page.evaluate("S.p.scene.tracks.map(t=>t.id)")
            page.locator('[data-page="effects"]').click()
            page.locator('[data-skill-tab="scene"]').click()
            page.locator(".skill-workflow-guide").wait_for()
            assert "技能预览" in page.locator(".skill-workflow-guide").inner_text()
            wait_for(page, "!skillPlans.get(S.p.id)?.loading")
            assert page.evaluate("S.p.scene.tracks.map(t=>t.id)") == manual_track_ids, "Loading an official plan must not replace a manual scene"
            page.locator("#add-effect").click()
            page.locator('[data-skill-pick]').first.wait_for()
            effect_ref = page.locator('[data-skill-pick]').first.get_attribute('data-skill-pick')
            page.locator('[data-skill-pick]').first.click()
            assert page.evaluate("S.p.scene.tracks.at(-1).ref") == effect_ref
            page.locator("#add-actor").click()
            page.locator('[data-skill-pick]').first.wait_for()
            actor_ref = page.locator('[data-skill-pick]').first.get_attribute('data-skill-pick')
            page.locator('[data-skill-pick]').first.click()
            assert page.evaluate("S.p.scene.tracks.at(-1).ref") == actor_ref
            assert page.locator('.skill-track').count() == len(manual_track_ids) + 2
            page.locator("#save").click()
            wait_for(page, "!S.dirty && !S.savePromise")
            page.screenshot(path=str(output / "05-skill-preview-picker.png"), full_page=True)
            page.locator('#compiled-preview').click()
            page.locator('#readback-play').wait_for()
            assert '技能组合' in page.locator('#modal-content h2').inner_text()
            page.screenshot(path=str(output / '05a-compiled-combination.png'),full_page=True)
            page.locator('.modal-close').click()
            color_result = page.evaluate("""async()=>{const c=document.createElement('canvas');c.width=c.height=1;const ctx=c.getContext('2d');ctx.fillStyle='rgb(100,200,250)';ctx.fillRect(0,0,1,1);const im=new Image();im.src=c.toDataURL();await im.decode();const result=previewImage(im,{colorTransform:[.5,20,20,45]});return [...result.getContext('2d').getImageData(0,0,1,1).data];}""")
            assert color_result == [70,120,170,255], color_result
            page.evaluate("async()=>{await saveNow();setProject(await api('/api/template-create',{id:'141007'}));S.page='effects';S.selected=S.p.effects.find(e=>e.soundEvents.some(ev=>ev.loop===-1)).id;render();}")
            loop_spec = page.evaluate("current().soundEvents.find(e=>e.loop===-1)")
            start_count=page.evaluate('window.__loopStarted.length')
            stop_count=page.evaluate('window.__audioStopped.length')
            page.locator('#play').click()
            wait_for(page,'S.playing')
            loop_started=page.evaluate(f'window.__loopStarted.slice({start_count})')
            stopped=page.evaluate(f'window.__audioStopped.slice({stop_count}).filter(Number.isFinite)')
            assert loop_started[0]['loop'] and abs(stopped[0]-loop_started[0]['when']-(loop_spec['end']-loop_spec['start'])/60)<.001
            page.locator('#play').click()
            page.locator('#compiled-preview').click()
            page.locator('#readback-play').wait_for()
            assert page.locator('#modal-content .notice').count()==0
            page.locator('.modal-close').click()
            page.screenshot(path=str(output / "06-native-loop-effect.png"), full_page=True)
            page.set_viewport_size({"width": 720, "height": 1000})
            page.locator('[data-page="voices"]').click()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            report = page.evaluate("({id:S.p.id,voices:S.p.voices.length,sounds:S.p.sounds.length,effects:S.p.effects.length})")
            report.update(eventTimingDeltaMs=delta, compiledAudioPlayback=True, realAudioDecoded=True, strictCSP=True, distributedExe=bool(args.exe), browserErrors=errors, fullAnimationBounds=bounds_report, preloadBeforePlayback=True, compiledCombination=True, nativeColorPixel=color_result, nativeLoopStopVerified=True, selectedEffectRef=effect_ref, selectedActorRef=actor_ref, manualScenePreserved=True)
            browser.close()
        (output / "library-ui-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        assert not errors, errors
        print(json.dumps(report, ensure_ascii=False))
    finally:
        if server:
            server.shutdown()
            server.server_close()
            worker.join(3)
        if process:
            try:
                req=urllib.request.Request(root + "/api/shutdown", data=b"{}", headers={"Content-Type":"application/json", "X-Studio-Token":session["token"]})
                urllib.request.urlopen(req, timeout=5).close()
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired, UnboundLocalError):
                pass
            finally:
                if process.poll() is None:process.terminate()


if __name__ == "__main__":
    main()
