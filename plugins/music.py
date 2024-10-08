import traceback
import config
from mirai import Image, MessageEvent, Voice
from plugin import Inject, PathArg, Plugin, top_instr, InstrAttr, route
import random
from pyncm_async import apis
from pyncm_async.apis.login import LoginViaCellphone
import os
import aiofile
import aiohttp
from pychorus import find_and_output_chorus
import uuid
from asyncify import asyncify
import pydub
from graiax import silkcoder
from utilities import get_logger, throttle_config

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from plugins.throttle import Throttle

logger = get_logger()

@route('音乐')
class Music(Plugin):
    throttle: Inject['Throttle']
    
    ncm_logined: bool

    def __init__(self) -> None:
        random.seed()
        self.ncm_logined = False

    async def login(self):
        logger.debug('music logining')
        try:
            await LoginViaCellphone(config.NCM_PHONE, config.NCM_PASSWORD)
        except:
            traceback.print_exc()
        logger.debug('music login success')

    @top_instr('来首(歌)?(?P<expr>.*?)', InstrAttr.NO_ALERT_CALLER)
    @throttle_config(name='听歌', max_cooldown_duration=10*60)
    async def rnd_music(self, expr: PathArg[str], event: MessageEvent, *kw: str):
        async with self.throttle as passed:
            if not passed: return

            if not self.ncm_logined:
                await self.login()
                self.ncm_logined = True

            if len(expr) > 0:
                kw = [expr, *kw]

            tracks: list
            if len(kw) == 0:
                tracks = (await apis.playlist.GetPlaylistInfo(532463786))['playlist']['tracks']
            else:
                tracks = (await apis.cloudsearch.GetSearchResult(' '.join(kw)))['result']['songs']
                # tracks.sort(key=lambda x: x['pop'], reverse=True)
                tracks = [tracks[0]]

            for _ in range(5):
                try:
                    track = random.choice(tracks)
                    track_name = track["name"]
                    logger.debug(f'music select -> {track_name}')
                    track_id = track['id']
                    track_img = track['al']['picUrl']
                    url = (await apis.track.GetTrackAudio(track_id))['data'][0]['url']
                    file_name = url.split("/")[-1]
                except: continue
                break
            else:
                raise RuntimeError('没找到音乐')

            await self.bot.send(event, [
                f'曲名: {track_name}',
                Image(url=track_img)
            ])
            logger.debug('music downloading')
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    assert resp.status == 200
                    data = await resp.read()
            file_path = self.path.data.cache.of_file(file_name)
            async with aiofile.async_open(file_path, "wb") as outfile:
                await outfile.write(data)
            
            rnd_str = uuid.uuid4()
            
            target_wav_file_path = self.path.data.cache.of_file(f'{rnd_str}.wav')
            target_silk_file_path = self.path.data.cache.of_file(f'{rnd_str}.silk')
            
            for clip_length in range(60, 0, -5):
                logger.debug('music analyzing, clip_length=', clip_length)
                res = await asyncify(find_and_output_chorus)(file_path, target_wav_file_path, clip_length)
                if res is not None: break
            else:
                audio = pydub.AudioSegment.from_mp3(file_path)
                audio = audio[0:20*1000]
                audio.export(target_wav_file_path, format='wav')

            logger.debug('music export silk format')
            await silkcoder.async_encode(target_wav_file_path, target_silk_file_path)
            logger.debug(f'music done -> {target_silk_file_path}')
            await self.bot.send(event, await Voice.from_local(target_silk_file_path))

            os.remove(target_wav_file_path)
            os.remove(target_silk_file_path)
