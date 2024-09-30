from event_types import EffectiveSpeechEvent
from mirai import GroupMessage, MessageEvent, Voice, Plain
from mirai.models.entities import GroupMember, MemberInfoModel

from plugin import AchvCustomizer, Inject, Plugin, delegate, fall_instr, top_instr, any_instr, InstrAttr, route
import random
import os
from graiax import silkcoder
from utilities import AchvEnum, AchvOpts, AchvRarity

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from plugins.achv import Achv
    from plugins.events import Events


class MeowAchv(AchvEnum):
    CACTUS = 0, '仙人球', '累计发送10000条消息', AchvOpts(rarity=AchvRarity.LEGEND, custom_obtain_msg='发大水了', target_obtained_cnt=10000, display='🌵', unit='条有效发言')
    FULL_LEVEL = 1, '一百昏', '群等级达到100级', AchvOpts(rarity=AchvRarity.LEGEND, custom_obtain_msg='满级了', display='💯', locked=True, dynamic_deletable=True)

# 10000 -> rare

@route('猫叫')
class Meow(Plugin, AchvCustomizer):
    achv: Inject['Achv']
    events: Inject['Events']
    
    @top_instr('叫一声', InstrAttr.NO_ALERT_CALLER)
    async def speak(self, event: MessageEvent):
        audio_name = random.choice(os.listdir(self.path.data))
        audio_path = self.path.data.of_file(audio_name)
        
        target_silk_file_path = self.path.data.cache.of_file(f'{os.path.splitext(audio_name)[0]}.silk')

        await silkcoder.async_encode(audio_path, target_silk_file_path)
        await self.bot.send(event, await Voice.from_local(target_silk_file_path))

        os.remove(target_silk_file_path)

    @any_instr(InstrAttr.NO_ALERT_CALLER)
    async def auto_speak(self, event: MessageEvent):
        if random.random() > 0.1: return
        for c in event.message_chain:
            if isinstance(c, Plain) and any([kw in c.text for kw in ('喵', '早', '呜', '咬')]):
                break
        else: return
        await self.speak(event)

    @any_instr()
    async def level_award(self, member: GroupMember):
        info: MemberInfoModel = await self.bot.member_info(member.group.id, member.id).get()
        if info.active.temperature == 100:
            await self.achv.submit(MeowAchv.FULL_LEVEL)

    @delegate()
    async def is_achv_deletable(self, e: AchvEnum, member: GroupMember):
        info: MemberInfoModel = await self.bot.member_info(member.group.id, member.id).get()
        if e is MeowAchv.FULL_LEVEL:
            return info.active.temperature != 100
        return False

    @fall_instr()
    async def falled(self, event: GroupMessage):
        texts = [c.text for c in event.message_chain if isinstance(c, Plain)]
        text_len = len(set(''.join(texts)))
        if text_len <= 5 or text_len >= 70:
            return
        await self.achv.submit(MeowAchv.CACTUS)
        await self.events.emit(EffectiveSpeechEvent())

        