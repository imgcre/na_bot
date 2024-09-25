import asyncio
import io
from mirai import Image
from plugin import InstrAttr, Plugin, autorun, delegate, enable_backup, route
from pyppeteer import launch
import urllib.parse
import json
import time
import base64
import imageio
import statistics

from utilities import SourceOp, get_logger

logger = get_logger()

# ./.vscode/settings.json ["terminal.integrated.env.windows"]
# $env:PYPPETEER_CHROMIUM_REVISION=1226537
# https://vikyd.github.io/download-chromium-history-version/#/

@route('渲染')
@enable_backup
class Renderer(Plugin):
    api_base: str = 'http://localhost:5173' # D:\projects\js\p-bot-fe
    render_scale: float = 2

    # def __init__(self):
    #     self.render_lock = asyncio.Lock()

        

    @autorun
    async def startup(self):
        self.render_lock = asyncio.Lock()

        self.browser = await launch(
            headless=False,
            executablePath=r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            args=[
                '--headless',
                '--disable-web-security', 
                '--enable-gpu', 
                '--no-sandbox',
                '--use-gl=angle',
                '--use-angle=gl',
                '--enable-unsafe-webgpu',
                '--disable-dev-shm-usage',
                '--disable-setuid-sandbox',
                '--disable-features=IsolateOrigins',
                '--disable-site-isolation-trials',

                '--hide-scrollbars',
                # '--autoplay-policy=no-user-gesture-required',

            ])

    @delegate(InstrAttr.BACKGROUND)
    async def render_as_task(self, op: SourceOp, *, url: str, data=None, target_selector='#target', done_selector='#done', 
            api_base=None, fullpage=False, duration: float=None, keep_last=False,
            playback_rate=1):
        b64_img = await self.render(
            url, data=data, target_selector=target_selector, done_selector=done_selector, api_base=api_base,
            fullpage=fullpage, duration=duration, keep_last=keep_last, playback_rate=playback_rate
        )
        await op.send([
            Image(base64=b64_img)
        ])

    async def render(
            self, url, *, data=None, target_selector='#target', done_selector='#done', 
            api_base=None, fullpage=False, duration: float=None, keep_last=False,
            playback_rate=1
        ):

        # https://developer.mozilla.org/en-US/docs/Web/API/Animation/playbackRate
        async with self.render_lock:
            start = time.time()
            page = await self.browser.newPage()
            if api_base is None:
                api_base = self.api_base
            try:
                await page.evaluateOnNewDocument(f'() => window.renderData={json.dumps(data)}')

                # await page.enable_debugger()

                if duration is not None:
                    await page.pause_animation()

                await page.goto(urllib.parse.urljoin(api_base, url))

                # await page.pause_script()
                
                # render_scale = self.render_scale
                render_scale = 2

                if duration is not None:
                    render_scale = 1

                async def waitSelectors():
                    if not fullpage:
                        # await page.pause_script()
                        logger.info('waitSelectors')
                        # await page.resume_script()
                        await page.waitForSelector(done_selector)
                        await page.waitForSelector(target_selector)
                    ...

                if not fullpage:
                    await page.addStyleTag({'content': f':root {{font-size: {render_scale}px}}'})
                    # await page.waitForSelector(done_selector)
                    # await page.waitForSelector(target_selector)
                    target = await page.querySelector(target_selector)
                else:
                    target = page

                if duration is not None:

                    e = asyncio.Event()

                    async def wait_animation():
                        await asyncio.sleep(duration)
                        e.set()
                        ...

                    # await page.pause_script()

                    frames = await target.screencast({
                        'omitBackground': True,
                        'event': e,
                        'waitReady': waitSelectors(),
                        'onStart': lambda: asyncio.create_task(wait_animation()),
                        'format': 'jpeg',
                        'playbackRate': playback_rate
                        # 'quality': 50
                    })

                    def b64_to_img(b64):
                        img_bytes = base64.b64decode(b64)
                        image_bio = io.BytesIO(img_bytes)
                        return imageio.imread(image_bio)
                        # return Image.open(image_bio)
                        ...

                    img_req = [b64_to_img(f['data']) for f in frames]

                    ts_seq = [f['timestamp'] for f in frames]

                    croped_img_req = []

                    croped_durations = [1 / 30]
                    
                    prev_ts = 0
                    for i, e in enumerate(zip(img_req, ts_seq)):
                        img, ts = e

                        if i == 0:
                            croped_img_req.append(img)
                            croped_durations.append(0)
                            prev_ts = ts
                        else:
                            if (ts - prev_ts) >= 1 / (30 * playback_rate):
                                
                                croped_img_req.append(img)
                                croped_durations.append((ts - prev_ts) * playback_rate)

                                prev_ts = ts
                            ...
                            ...

                        ...

                    average_duration = statistics.mean(croped_durations[1:])
                    average_fps = 1 / average_duration

                    if keep_last:
                        croped_durations[-2] = 5


                    logger.debug(f'{len(img_req)=} => {len(croped_img_req)=}, {average_fps=:.2f}')


                    buffered = io.BytesIO()

                    # first_img.save(buffered, format="GIF", save_all=True, append_images=remains_img, duration=durations, loop=0)

                    imageio.mimsave(buffered, croped_img_req, 'GIF', duration=croped_durations, loop=1)

                    img_str = base64.b64encode(buffered.getvalue())

                    

                    # return frames[0]['data']
                    return img_str
                else:
                    await waitSelectors()

                    return await target.screenshot({
                        'omitBackground': True,
                        'encoding': 'base64'
                    })
            finally:
                await page.close()
                end = time.time()
                logger.debug(f'elapsed {end-start:.2f}s')
