"""Real Edge integration: pixels, scaling and push settings transitions."""
import asyncio
import base64
import io
from PIL import Image
from playwright.async_api import async_playwright
from server import CAPTURE, PUSH

async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        try:
            page=await browser.new_page()
            await page.set_content('<canvas width="400" height="240"></canvas>')
            await page.evaluate('''() => {
                const c=document.querySelector('canvas').getContext('2d');
                c.fillStyle='red';c.fillRect(0,0,200,120);
                c.fillStyle='lime';c.fillRect(200,0,200,120);
                c.fillStyle='blue';c.fillRect(0,120,200,120);
                c.fillStyle='white';c.fillRect(200,120,200,120);
            }''')
            for half in (0,1,2):
                raw=base64.b64decode(await page.locator('canvas').evaluate(CAPTURE,half))
                if half == 1:
                    w,h=200,120
                    assert len(raw)==w*h
                    assert [raw[0],raw[w-1],raw[(h-1)*w],raw[-1]]==[224,28,3,255]
                else:
                    assert Image.open(io.BytesIO(raw)).size == ((400,240) if half==0 else (320,192))
            samples=[]
            complete=asyncio.Event()
            async def frame(encoded,half,duration):
                if encoded:
                    raw=base64.b64decode(encoded)
                    assert len(raw)==24000 if half == 1 else raw[:2]==b'\xff\xd8'
                    samples.append(half)
                    if len(samples)>=6: complete.set()
                return dict(active=True,fps=60,half=len(samples)>=3)
            await page.expose_function('__rogueFrame',frame)
            await page.evaluate('() => { window.__rogueCapture = ('+CAPTURE+'); }')
            await page.evaluate(PUSH,dict(selector='canvas',initial=dict(active=True,fps=60,half=False)))
            await asyncio.wait_for(complete.wait(),10)
            await page.evaluate('window.__rogueStreaming=false')
            assert samples[:3]==[False]*3 and all(samples[3:])
            print('OK: pixels, full/half resolution, push delivery and live settings')
        finally:
            await browser.close()

if __name__=='__main__': asyncio.run(main())
