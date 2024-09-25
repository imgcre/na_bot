from datetime import datetime
from mirai import MessageEvent, Plain
from plugin import AchvCustomizer, Inject, InstrAttr, Plugin, any_instr, delegate, route, top_instr
from utilities import AchvEnum, AchvOpts, AchvRarity, GroupMemberOp
from borax.calendars.festivals2 import FestivalLibrary, Festival as Fes
from dataclasses import dataclass
import re

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from plugins.achv import Achv

class FestivalAchv(AchvEnum):
    MID_AUTUMN_FESTIVAL = 0, '月饼', '在中秋节当天发送"中秋快乐"', AchvOpts(rarity=AchvRarity.RARE, display='🥮', dynamic_deletable=True)
    NATIONAL_DAY = 1, '国旗', '在国庆节当天发送"国庆快乐"', AchvOpts(rarity=AchvRarity.RARE, display='🇨🇳', dynamic_deletable=True)
    FURSUIT_FRIDAY = 2, '肉垫', '在毛毛星期五当天发送包含"毛五"的消息', AchvOpts(rarity=AchvRarity.UNCOMMON, display='🐾', dynamic_deletable=True)
class FursuitFriday():
    def countdown(self):
        today = datetime.now()
        days_ahead = 4 - today.weekday()  # 4代表周五
        if days_ahead < 0:  # 如果今天是周五，返回7天后
            days_ahead += 7
        return days_ahead, None
    
    @property
    def name(self):
        return '毛毛星期五'
    
@dataclass
class FestivalItem():
    festival: Fes
    trigger_regex: str
    associated_achv: FestivalAchv

@route('节日')
class Festival(Plugin, AchvCustomizer):
    achv: Inject['Achv']
    
    def __init__(self):
        self.library = FestivalLibrary.load_builtin()
        self.festivals = [
            FestivalItem(
                festival=self.library.get_festival('中秋节'),
                trigger_regex='中秋.*?快乐',
                associated_achv=FestivalAchv.MID_AUTUMN_FESTIVAL
            ),
            FestivalItem(
                festival=self.library.get_festival('国庆节'),
                trigger_regex='国庆.*?快乐',
                associated_achv=FestivalAchv.NATIONAL_DAY
            ),
            FestivalItem(
                festival=FursuitFriday(), 
                trigger_regex='毛五',
                associated_achv=FestivalAchv.FURSUIT_FRIDAY
            ),
        ]
        ...

    @any_instr(InstrAttr.NO_ALERT_CALLER)
    async def festival_achv(self, event: MessageEvent, op: GroupMemberOp):
        for item in self.festivals:
            days, _ = item.festival.countdown()
            if days == 0:
                if not await self.achv.has(item.associated_achv):
                    for c in event.message_chain:
                        if isinstance(c, Plain) and re.search(item.trigger_regex, c.text) is not None:
                            break
                    else: return
                    
                    await self.achv.submit(item.associated_achv, silent=True)
                    await op.nudge()

    @delegate()
    async def is_achv_deletable(self, e: AchvEnum):
        for item in self.festivals:
            if item.associated_achv is e:
                days, _ = item.festival.countdown()
                return days != 0
        return False

    def get_countdowns(self):
        return {item.festival.name: item.festival.countdown()[0] for item in self.festivals}

    @top_instr('节日测试')
    async def test_fes(self, name: str):
        library = FestivalLibrary.load_builtin()
        fes = library.get_festival(name)

        days, _ = fes.countdown()

        return [f'{days=}']
        ...