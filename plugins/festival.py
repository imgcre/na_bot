from datetime import datetime, date, timedelta
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
    SPRING_FESTIVAL = 3, '爆竹', '在春节当天发送"新年快乐"', AchvOpts(rarity=AchvRarity.RARE, display='🧨', dynamic_deletable=True)
    CHRISTMAS = 4, '圣诞树', '在圣诞节当天发送"圣诞快乐"', AchvOpts(rarity=AchvRarity.RARE, display='🎄', dynamic_deletable=True)

class FursuitFriday():
    def countdown(self, date_obj: date = None):
        if date_obj is None:
            date_obj = date.today()
        days_ahead = 4 - date_obj.weekday()  # 4代表周五
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
    duration_days: int = 1

    def is_available(self):
        offset_date = date.today() - timedelta(days=self.duration_days-1)
        days, _ = self.festival.countdown(offset_date)
        return days < self.duration_days

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
                associated_achv=FestivalAchv.NATIONAL_DAY,
                duration_days=7
            ),
            FestivalItem(
                festival=FursuitFriday(), 
                trigger_regex='毛五',
                associated_achv=FestivalAchv.FURSUIT_FRIDAY
            ),
            FestivalItem(
                festival=self.library.get_festival('春节'),
                trigger_regex='新年.*?快乐',
                associated_achv=FestivalAchv.SPRING_FESTIVAL,
                duration_days=15
            ),
            FestivalItem(
                festival=self.library.get_festival('圣诞节'),
                trigger_regex='圣诞.*?快乐|christmas',
                associated_achv=FestivalAchv.CHRISTMAS
            ),
        ]
        ...

    @any_instr(InstrAttr.NO_ALERT_CALLER)
    async def festival_achv(self, event: MessageEvent, op: GroupMemberOp):
        for item in self.festivals:
            if item.is_available():
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
                return not item.is_available()
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