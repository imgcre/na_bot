import math
from typing import Callable, ClassVar, Dict, Final, TypeVar
from mirai import GroupMessage, Image
from mirai.models.entities import GroupMember
from plugin import Inject, Plugin, delegate, enable_backup, fall_instr, top_instr, any_instr, InstrAttr, route
from dataclasses import asdict, dataclass
import time
from utilities import AchvEnum, AchvOpts, AchvRarity, get_delta_time_str
from mirai.models.message import MarketFace

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from plugins.renderer import Renderer
    from plugins.check_in import CheckIn
    from plugins.achv import Achv
    from plugins.ai_ext import AiExt

class RestAchv(AchvEnum):
    SLEEPTALKING = 0, '梦呓', '在睡觉状态中发言', AchvOpts(condition_hidden=True, custom_obtain_msg='说了句梦话', display='💭')
    FALSE_AWAKING = 1, '盗梦空间', '在睡觉状态中使用【#睡觉】指令', AchvOpts(condition_hidden=True, custom_obtain_msg='进入了盗梦空间', display='🛸')
    LOST_DOMAIN = 2, '跌入梦境', '累积睡眠10万分钟', AchvOpts(rarity=AchvRarity.LEGEND, custom_obtain_msg='来到了梦境中意识的边缘', target_obtained_cnt=100000, locked=True, unit='分钟睡眠', display='🍂')
    SLEEPING = 3, '睡觉中', '成员在睡觉状态中时自动获得, 醒来自动删除', AchvOpts(display_pinned=True, locked=True, hidden=True, display='💤', display_weight=-1)
    ...

@dataclass
class RestInfo():
    who: GroupMember
    rest_tsc: float # 开始休息的时间点, 单位: 秒

    MAX_REST_TIME: ClassVar[int] = 60 * 60 * 8
    INVALID_REST_TIME_THRESHOLD: ClassVar[int] = 60 * 60 * 18

    def get_span(self):
        return min(self.MAX_REST_TIME, time.time() - self.rest_tsc)
    
    def is_invalid(self):
        return time.time() - self.rest_tsc > self.INVALID_REST_TIME_THRESHOLD

    def get_rest_time_str(self):
        prefix = ''
        span = self.get_span()
        if span >= self.MAX_REST_TIME:
            prefix = '超过'
        return f'{prefix}{get_delta_time_str(self.get_span(), use_seconds=False)}'

@dataclass
class RestHistory():
    who: GroupMember
    total_span: float = 0
    last_awake_ts: float = 0

@dataclass
class ConvertedRestHistory():
    name: str
    avatar_url: str
    timespan: int
    sleeping: bool

    @staticmethod
    def from_rest_history(history: 'RestHistory', sleeping: bool):
        return ConvertedRestHistory(
            name=history.who.get_name(),
            avatar_url=history.who.get_avatar_url(),
            timespan=history.total_span,
            sleeping=sleeping,
        )

@route('休息')
@enable_backup
class Rest(Plugin):
    bed: Dict[int, Dict[int, RestInfo]] = {}
    history: Dict[int, Dict[int, RestHistory]] = {}
    achv: Inject['Achv']
    ai_ext: Inject['AiExt']
    check_in: Inject['CheckIn']

    MIN_SLEEP_DURATION: Final[float] = 60

    @top_instr('睡觉|晚安')
    async def say(self):
        if not await self.check_in.is_checked_in_today():
            return '需要先【#签到】才能睡觉，问就是给新功能引流'
        return await self.go_to_sleep()

    @any_instr()
    async def sleep_via_motion(self, event: GroupMessage):
        for c in event.message_chain:
            if isinstance(c, MarketFace) and c.id == 236744 and c.name == '[晚安]':
                await self.check_in.do_check_in(silent=True)
                return await self.go_to_sleep()
                ...
        # 236744 [晚安]
        ...
    
    @delegate(InstrAttr.FORECE_BACKUP)
    async def go_to_sleep(self, who: GroupMember):
        def try_get_rest_history():
            if who.group.id not in self.history:
                return
            history_of_group = self.history[who.group.id]
            if who.id not in history_of_group:
                return
            return history_of_group[who.id]

        rest_history = try_get_rest_history()
        if rest_history is not None:
            timedelta_since_last_awake = time.time() - rest_history.last_awake_ts
            MIN_REST_TIMEDELTA = 60 * 60 * 2
            if timedelta_since_last_awake < MIN_REST_TIMEDELTA:
                return f'现在还不能睡觉, 请{get_delta_time_str(MIN_REST_TIMEDELTA - timedelta_since_last_awake, use_seconds=False)}后再试'
            ...

        if who.group.id not in self.bed:
            self.bed[who.group.id] = {}
        bed_of_group = self.bed[who.group.id]
        if who.id in bed_of_group:
            await self.achv.submit(RestAchv.FALSE_AWAKING)
            return
        bed_of_group[who.id] = RestInfo(who=who, rest_tsc=time.time())

        await self.achv.submit(RestAchv.SLEEPING, silent=True)

        # return random.choice([
        #     '夜深了，快安心休息吧。晚安！',
        #     '道一声晚安，望你一切安好！',
        #     '想送你一颗星星，有我给你俏皮的祝福。',
        #     '情绪舒畅，安然入眠。',
        #     '晚的黑暗，消除你一天的疲劳。',
        #     '好梦即将来到，闭上眼睛睡。',
        #     '晚安，愿你今夜入睡，梦境美满。',
        #     '愿你今晚留下思考，醒来收获智慧，晚安。',
        #     '将烦忧留在门外，让平静与欢乐进入你的世界，晚安。',
        #     '抛烦恼忧愁，莫让小事扰美梦。',
        #     '愿你日日乐陶陶，祝你夜夜梦美好。',
        #     '轻松入眠，美梦香甜！',
        #     '醒时就笑，入梦就甜。',
        #     '开心和你常伴，美梦和你相连。',
        #     '送走一天的忙碌，忘掉一天的烦恼。',
        #     '愿你每个梦里，都有笑容。',
        #     '祝福化作天上星，好梦连连数不清。',
        #     '安静欣赏夜景，将喧闹归零。',
        #     '不要奋斗太晚，好好保重身体，晚安。',
        #     '洗个澡，铺好床，今晚做梦遇周公。',
        #     '月光抚摸你，你不会孤单。',
        #     '让我们红尘作伴，睡得白白胖胖。',
        #     '天上的繁星，为你演奏一首首催眠曲。',
        # ])

    @top_instr('睡觉榜', InstrAttr.NO_ALERT_CALLER)
    async def board(self, event: GroupMessage, renderer: Inject['Renderer']):
        group_id = event.group.id
        merged_history: Dict[int, RestHistory] = {}

        members = (await self.bot.member_list(event.group.id)).data

        T = TypeVar('T')
        async def acc(coll: Dict[int, T], fn: Callable[[T], float]):
            for member_id in coll:
                if not any([m.id == member_id for m in members]): continue
                if member_id not in merged_history:
                    mem = await self.bot.get_group_member(group_id, member_id)
                    merged_history[member_id] = RestHistory(who=mem)
                merged_history[member_id].total_span += fn(coll[member_id])

        if group_id in self.bed:
            await acc(self.bed[group_id], lambda el: el.get_span())

        if group_id in self.history:
            await acc(self.history[group_id], lambda el: el.total_span)

        rank = list(merged_history.values())
        rank.sort(key=lambda el: el.total_span, reverse=True)
        rank = rank[:10]
        rank = [asdict(ConvertedRestHistory.from_rest_history(el, el.who.id in self.bed[group_id])) for el in rank]
        b64_img = await renderer.render('rest-rank', data=rank)
        return [
            Image(base64=b64_img)
        ]
    
    @top_instr('床', InstrAttr.NO_ALERT_CALLER)
    async def print_bed(self, event: GroupMessage):
        who = event.sender
        if who.group.id not in self.bed:
            self.bed[who.group.id] = {}
        bed_of_group = self.bed[who.group.id]
        li = [f'(¦3[▓▓] {m.who.member_name} {m.get_rest_time_str()}' for m in bed_of_group.values() if not m.is_invalid()]
        if len(li) == 0:
            return '现在没有人在休息'
        return '\n'.join(li)

    @fall_instr()
    async def falled(self, event: GroupMessage):
        who = event.sender
        if not(who.group.id in self.bed and who.id in self.bed[who.group.id]):
            return
        
        for c in event.message_chain:
            if isinstance(c, MarketFace) and c.id == 236744 and c.name == '[晚安]':
                return

        info = self.bed[who.group.id][who.id]

        if info.get_span() < self.MIN_SLEEP_DURATION:
            await self.achv.submit(RestAchv.SLEEPTALKING)


    @any_instr()
    async def awake(self, event: GroupMessage):
        who = event.sender
        if not(who.group.id in self.bed and who.id in self.bed[who.group.id]):
            return
        info = self.bed[who.group.id][who.id]

        if info.get_span() < self.MIN_SLEEP_DURATION:
            return
        
        self.backup_man.set_dirty()
        self.bed[who.group.id].pop(who.id, None)
        if len(self.bed[who.group.id]) == 0:
            self.bed.pop(who.group.id, None)

        if who.group.id not in self.history:
            self.history[who.group.id] = {}
        history_of_group = self.history[who.group.id]
        if who.id not in history_of_group:
            history_of_group[who.id] = RestHistory(who=who)
        rest_history = history_of_group[who.id]
        rest_history.last_awake_ts = time.time()

        await self.achv.remove(RestAchv.SLEEPING, force=True)

        if info.is_invalid():
            return [
                # Image(path=img_path),
                f'由于休息时间过长, 本次休息作废'
            ]
        
        rest_history.total_span += info.get_span()
        
        # img_path = random.choice([
        #     self.path.data.of_file(name)
        #     for name in os.listdir(self.path.data) 
        # ])

        await self.achv.submit(RestAchv.LOST_DOMAIN, override_obtain_cnt=math.floor(rest_history.total_span // 60))

        msg = [
            # Image(path=img_path),
            f'你休息了{info.get_rest_time_str()}'
        ]

        if info.get_span() >= 60 * 60 * 6:
            await self.ai_ext.chat(msg=msg)
            return

        # return [*msg, '，由于休息时长不达标，未触发AI']
