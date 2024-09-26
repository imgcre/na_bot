from dataclasses import dataclass, field
from typing import List, Optional
import typing
from mirai import At, GroupMessage
from plugin import AchvCustomizer, Inject, Plugin, any_instr, delegate, enable_backup, nudge_instr, top_instr, route, InstrAttr
from mirai.models.message import Image
from mirai.models.entities import GroupMember
from utilities import AchvEnum, AchvOpts, AchvRarity, AdminType, GroupLocalStorage, GroupLocalStorageAsEvent, GroupMemberOp
import pytz
from datetime import datetime
import time
import calendar
from mirai.models.events import NudgeEvent
from mirai.models.message import MarketFace

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from plugins.renderer import Renderer
    from plugins.achv import Achv
    from plugins.admin import Admin

class CheckInAchv(AchvEnum):
    CHAMPION = 0, '火急火燎', '获得某日签到第一名', AchvOpts(display='🚀')
    CONSECUTIVE_DAYS_5 = 1, '连五鞭', '连续签到五天', AchvOpts(rarity=AchvRarity.UNCOMMON, custom_obtain_msg='打出了闪电五连鞭', display='⚡')
    PERFECT_ATTENDANCE = 2, '全勤', '连续签满一个自然月', AchvOpts(rarity=AchvRarity.RARE, display='🈵')
    UNITY_IS_STRENGTH = 3, '众人拾柴火焰高', '同一天有50人及以上参与签到', AchvOpts(rarity=AchvRarity.EPIC)
    HUGGING_FACE = 4, '助人为乐', '帮助他人签到100次', AchvOpts(rarity=AchvRarity.RARE, custom_obtain_msg='抱了抱大家', target_obtained_cnt=100, display='🤗')
    CHECKED_IN_TODAY = 5, '已签到', '今日已签到时自动获取', AchvOpts(display_pinned=True, locked=True, hidden=True, display='✨️', display_weight=-1, dynamic_obtained=True)

class AlreadyCheckInException(Exception):
    def __init__(self):
        super().__init__('今天已经签到过了')

class CheckInRequiredException(Exception):
    ...

class BadTimeException(Exception):
    ...

@dataclass
class CheckInMan():
    checkin_ts: List[float] = field(default_factory=list)

    def get_checkin_ts_today(self):
        if len(self.checkin_ts) == 0: return None
        last_checkin_ts = self.checkin_ts[-1]
        if last_checkin_ts < self.get_start_ts_of_today(): return None
        return last_checkin_ts


    def check_in(self):
        if self.get_checkin_ts_today() is not None:
            raise AlreadyCheckInException()
        now = time.time()
        self.checkin_ts.append(now)
        return now
    
    def re_check_in(self, target_ts: float):
        # if self.get_checkin_ts_today() is None:
        #     raise CheckInRequiredException()
        if target_ts > time.time():
            raise BadTimeException()
        start_ts_of_that_day = self.get_start_ts_of_today(ts=target_ts)
        end_ts_of_that_day = start_ts_of_that_day + 60 * 60 * 24
        if any([e >= start_ts_of_that_day and e < end_ts_of_that_day for e in self.checkin_ts]):
            raise AlreadyCheckInException()
        self.ordered_insert(self.checkin_ts, target_ts)

    @staticmethod
    def ordered_insert(li: list, e):
        try:
            target_index = list(x > e for x in li).index(True)
            li.insert(target_index, e)
        except:
            li.append(e)

    @property
    def consecutive_days(self):
        one_day_span = 60 * 60 * 24
        curr_ts = self.get_start_ts_of_today()
        cnt = 0
        while cnt < len(self.checkin_ts):
            if self.checkin_ts[-(cnt+1)] < curr_ts:
                break
            cnt += 1
            curr_ts -= one_day_span
        return cnt

    @property
    def checkin_ts_this_month(self):
        return [ts for ts in self.checkin_ts if ts >= self.get_start_ts_of_this_month()]

    @classmethod
    def get_start_ts_of_today(cls, *, ts=None):
        return cls.get_start_ts_of(hour=0, minute=0, second=0, microsecond=0, ts=ts)
    
    @classmethod
    def get_start_ts_of_this_month(cls, *, ts=None):
        return cls.get_start_ts_of(hour=0, minute=0, second=0, microsecond=0, day=1, ts=ts)
    
    @classmethod
    def if_full_checked_in_this_month(cls, consecutive_days):
        tz = pytz.timezone('Asia/Shanghai')
        today = datetime.now(tz=tz)
        last_day_this_month = calendar.monthrange(today.year, today.month)[1]
        return consecutive_days >= last_day_this_month and today.day == last_day_this_month

    @staticmethod
    def get_start_ts_of(*, ts=None, **kwargs):
        tz = pytz.timezone('Asia/Shanghai')
        if ts is None:
            ts = time.time()
        today = datetime.fromtimestamp(ts, tz=tz)
        start = today.replace(**kwargs)
        return start.timestamp()


@route('check_in')
@enable_backup
class CheckIn(Plugin, AchvCustomizer):
    gls: GroupLocalStorage[CheckInMan] = GroupLocalStorage[CheckInMan]()
    renderer: Inject['Renderer']
    achv: Inject['Achv']
    admin: Inject['Admin']

    @delegate()
    async def is_checked_in_today(self, man: Optional[CheckInMan]):
        return man is not None and man.get_checkin_ts_today() is not None

    async def is_achv_obtained(self, e: 'AchvEnum'):
        if e is CheckInAchv.CHECKED_IN_TODAY:
            return await self.is_checked_in_today()
        return False
    
    @delegate()
    async def get_checkin_ts_today(self, man: Optional[CheckInMan]):
        if man is None:
            return None
        return man.get_checkin_ts_today()

    @top_instr('签到|起床|醒来', InstrAttr.NO_ALERT_CALLER)
    async def check_in(self):
        await self.do_check_in()

    @top_instr('帮群友签到', InstrAttr.NO_ALERT_CALLER)
    async def check_in_proxy(self, at: At):
        member = await self.member_from(at=at)
        async with self.override(member):
            await self.do_check_in(raise_error=True)
        await self.achv.submit(CheckInAchv.HUGGING_FACE)
    
    @any_instr(InstrAttr.INTERCEPT_EXCEPTIONS)
    async def check_in_via_motion(self, event: GroupMessage):
        for c in event.message_chain:
            if isinstance(c, MarketFace) and c.id == 236744 and c.name == '[被拖走]':
                await self.do_check_in(raise_error=True)
    
    @nudge_instr(InstrAttr.INTERCEPT_EXCEPTIONS)
    async def nudge(self, event: NudgeEvent):
        if event.target != self.bot.qq:
            return
        await self.do_check_in(raise_error=True)
    
    @top_instr('补签', InstrAttr.NO_ALERT_CALLER)
    async def re_check_in_cmd(self):
        return '还在写，别着急！'
    
    @top_instr('取消签到', InstrAttr.FORECE_BACKUP)
    async def cancel_check_in_cmd(self, man: CheckInMan):
        async with self.admin.privilege(type=AdminType.SUPER):
            man.checkin_ts = [ts for ts in man.checkin_ts if ts < man.get_start_ts_of_today()]
        
    # @admin
    # @top_instr('帮群友补签', InstrAttr.NO_ALERT_CALLER, InstrAttr.FORECE_BACKUP)
    # async def re_check_in_to_cmd(self, at: At, year: int, month: int, day: int):
    #     member = await self.member_from(at=at)
    #     async with self.override(member):
    #         return await self.re_check_in(year=year, month=month, day=day)
    
    @delegate()
    async def re_check_in(self, man: CheckInMan, member: GroupMember, *, year: int, month: int, day: int):
        tz = pytz.timezone('Asia/Shanghai')
        dt = datetime(year, month, day, 12, tzinfo=tz)

        try:
            man.re_check_in(dt.timestamp())
        except AlreadyCheckInException:
            return f'{member.member_name}在{year}/{month}/{day}那天已经签到过了'
        except BadTimeException:
            return f'签到日期不正确'

        consecutive_days = man.consecutive_days
        if consecutive_days >= 5:
            await self.achv.submit(CheckInAchv.CONSECUTIVE_DAYS_5)

        if man.if_full_checked_in_this_month(consecutive_days):
            await self.achv.submit(CheckInAchv.PERFECT_ATTENDANCE)

        b64_img = await self.renderer.render('check-in', duration=5, keep_last=True, data={
            'ranking': 99,
            'checkin_ts_this_month': man.checkin_ts_this_month,
            'avatar_url': member.get_avatar_url()
        })
        return [
            Image(base64=b64_img)
        ]

    @delegate(InstrAttr.FORECE_BACKUP)
    async def do_check_in(self, glse_: gls.event_t(), op: GroupMemberOp, *, raise_error = False, silent = False):

        glse = typing.cast(GroupLocalStorageAsEvent[CheckInMan], glse_)
        man = glse.get_or_create_data()
        try:
            checkin_tsc = man.check_in()
        except AlreadyCheckInException:
            if raise_error:
                raise
            return [At(target=op.member.id), ' 今天已经签到过了']
        ranking = sorted([
            ts for v in glse.get_data_of_group().values() 
            if (ts := v.get_checkin_ts_today()) is not None
        ]).index(checkin_tsc) + 1

        if ranking == 1:
            await self.achv.submit(CheckInAchv.CHAMPION, silent=silent)

        if ranking >= 50:
            for member_id, man in [
                it for it in glse.get_data_of_group().items() if it[1].get_checkin_ts_today() is not None
            ]:
                member = await self.member_from(member_id=member_id)
                async with self.override(member):
                    await self.achv.submit(CheckInAchv.UNITY_IS_STRENGTH, silent=True)
        
        consecutive_days = man.consecutive_days
        if consecutive_days >= 5:
            await self.achv.submit(CheckInAchv.CONSECUTIVE_DAYS_5, silent=silent)

        if man.if_full_checked_in_this_month(consecutive_days):
            await self.achv.submit(CheckInAchv.PERFECT_ATTENDANCE, silent=silent)

        await op.nudge()
        await self.achv.update_member_name()

        if not silent:
            await self.renderer.render_as_task(url='check-in', duration=5, keep_last=True, data={
                'ranking': ranking,
                'checkin_ts_this_month': man.checkin_ts_this_month,
                'avatar_url': op.get_avatar()
            })
            # b64_img = await self.renderer.render('check-in', duration=5, keep_last=True, data={
            #     'ranking': ranking,
            #     'checkin_ts_this_month': man.checkin_ts_this_month,
            #     'avatar_url': op.get_avatar()
            # })
            # return [
            #     Image(base64=b64_img)
            # ]
            

