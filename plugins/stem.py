import time

from mirai import GroupMessage, Image, Plain

import mirai.models.message
from mirai.models.entities import GroupMember
from plugin import Plugin, top_instr, any_instr, InstrAttr, route, PathArg
import random
import random
from PIL import Image as img
from PIL.Image import Image as PImage
import aiohttp
import aiofile
from enum import Enum, auto

from utilities import get_logger

logger = get_logger()

class Dir(Enum):
    小威 = auto()

@route('梗')
class Stem(Plugin):
    last_run_time: int

    def __init__(self) -> None:
        self.last_run_time = time.time()

    @top_instr('(?P<which>原神|vscode).*?启动.*?', InstrAttr.NO_ALERT_CALLER)
    async def impa(self, which: PathArg[str]):
        pic_name = 'impa.jpg' if which == '原神' else 'vscode.jpg'
        return [
            mirai.models.message.Image(path=self.path.data.of_file(pic_name))
        ]
    
    @top_instr('关机|关闭', InstrAttr.NO_ALERT_CALLER)
    async def shutdown(self):
        return [
            mirai.models.message.Image(path=self.path.data.of_file('关机.jpg'))
        ]
    
    @any_instr(InstrAttr.NO_ALERT_CALLER)
    async def auto_impa(self, event: GroupMessage):
        for c in event.message_chain:
            if isinstance(c, Plain):
                if '行' in c.text and random.random() < 0.2:
                    return [
                        mirai.models.message.Image(path=self.path.data.of_file('行.jpg'))
                    ]

    # @any_instr(InstrAttr.NO_ALERT_CALLER)
    # async def auto_impa(self, event: GroupMessage):
    #     now = time.time()
    #     if event.sender.id == 928079017 and (now - self.last_run_time > 60 * 60):
    #         self.last_run_time = now
    #         return await self.impa()

    @top_instr('打卡', InstrAttr.NO_ALERT_CALLER)
    async def check_in(self, member: GroupMember):
        avatar_url = member.get_avatar_url()
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url) as resp:
                assert resp.status == 200
                data = await resp.read()
        file_name = f'{member.id}.jpg'
        file_path = self.path.data.cache.of_file(file_name)
        async with aiofile.async_open(file_path, "wb") as outfile:
            await outfile.write(data)
        
        im_front: PImage = img.open(self.path.data.of_file('check_in_front.png'))
        im_target: PImage = img.new('RGBA', im_front.size, (0, 0, 0, 0))
        im_avatar: PImage = img.open(file_path)

        im_avatar.thumbnail((139, 139), img.Resampling.LANCZOS)
        im_target.paste(im_avatar, (317, 429 - 22))
        im_target.paste(im_front, (0, 0), im_front)

        target_file_name = f'{member.id}.png'
        target_file_path = self.path.data.cache.of_file(target_file_name)
        im_target.save(target_file_path, "PNG")

        return [
            mirai.models.message.Image(path=target_file_path)
        ]

    @any_instr()
    async def coll_小威(self, event: GroupMessage):
        who = event.sender
        if who.id != 13975418:
            return
        for c in event.message_chain:
            if isinstance(c, Image):
                p = await c.download(directory=self.path.data[Dir.小威])
        