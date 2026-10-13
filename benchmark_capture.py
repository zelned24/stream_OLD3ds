"""Compare capture paths without touching the user's game profile."""
import asyncio
import base64
import time
from playwright.async_api import async_playwright
from server import encode, CAPTURE
from PIL import Image

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel='msedge',headless=True)
        page = await browser.new_page(viewport={'width':800,'height':480})
        await page.goto('https://pokerogue.net')
        canvas = page.locator('canvas').first
        await canvas.wait_for()
        await asyncio.sleep(3)
        for mode in ['screenshot','canvas']:
            timings=[]
            for _ in range(20):
                start=time.perf_counter()
                if mode=='screenshot':
                    encode(await canvas.screenshot())
                else:
                    frame = base64.b64decode(await canvas.evaluate(CAPTURE))
                timings.append((time.perf_counter()-start)*1000)
            print(f'{mode}: mean={sum(timings)/len(timings):.1f}ms max={max(timings):.1f}ms',flush=True)
        preview = Image.frombytes('P', (400,240), frame)
        preview.putpalette([channel for v in range(256)
                            for channel in ((v>>5)*255//7, ((v>>2)&7)*255//7, (v&3)*85)])
        preview.convert('RGB').save('capture-check.png')
        print(f'Canvas colors={len(set(frame))}; bytes={len(frame)}', flush=True)
        await browser.close()

if __name__=='__main__':
    asyncio.run(main())
