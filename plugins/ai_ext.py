import asyncio
import random
import re
from typing import Final,  Optional
from event_types import EffectiveSpeechEvent
from mirai import GroupMessage
from plugin import Plugin, any_instr, delegate, InstrAttr, route, enable_backup, Inject
from mirai.models.entities import GroupMember

from typing import TYPE_CHECKING

from utilities import AchvRarity, AchvOpts, GroupLocalStorage, GroupMemberOp, MsgOp, SourceOp, ThrottleMan, get_delta_time_str, AchvEnum, handler
if TYPE_CHECKING:
    from plugins.achv import Achv
    from plugins.events import Events
    from plugins.gpt import Gpt
    from plugins.admin import Admin

class AiExtAchv(AchvEnum):
    AI_COOLDOWN = 0, 'AI冷却中', '主动和bot对话功能在冷却状态下时自动获得', AchvOpts(display_pinned=True, locked=True, hidden=True, display='🆒', display_weight=-1)
    EDGE = 1, '边缘', '在AI的CD只有一分钟时发起对话获得', AchvOpts(rarity=AchvRarity.UNCOMMON, display='⌛', custom_obtain_msg='差点就……')

@route('AI拓展')
@enable_backup
class AiExt(Plugin):
    gls_throttle: GroupLocalStorage[ThrottleMan] = GroupLocalStorage[ThrottleMan]()

    achv: Inject['Achv']
    events: Inject['Events']
    gpt: Inject['Gpt']
    admin: Inject['Admin']
    

    MAX_COOLDOWN_DURATION: Final = 6 * 60 * 60
    MIN_COOLDOWN_DURATION: Final = 10 * 60

    # 单位是秒
    SPEEDUP_LOOKUP: Final = {
        AchvRarity.COMMOM: 30 * 60,
        AchvRarity.UNCOMMON: 10 * 60,
        AchvRarity.RARE: 5 * 60,
        AchvRarity.EPIC: 2 * 60,
    }

    SPEEDUP_EFFECTIVE_SPEECH: Final = 10 * 60

    MAX_BREAKDOWN: Final = 5

    MIN_BREAKDOWN_PROB_WORDS: Final = 5
    MAX_BREAKDOWN_PROB_WORDS: Final = 30

    def __init__(self):
        self.ai_resp_msg_ids: list[int] = []

    @delegate()
    async def chat(self, event: GroupMessage, *, msg: list):
        res = await self.gpt.response_with_ai(msg=msg)
        if res is not None:
            await self.bot.send(event, res)

    @handler
    @delegate(InstrAttr.FORECE_BACKUP)
    async def on_effective_speech(self, event: EffectiveSpeechEvent, man: ThrottleMan):
        man.inc_effective_speech_cnt()

    @delegate()
    async def check_avaliable(self, man: Optional[ThrottleMan], member_op: GroupMemberOp, msg_op: Optional[MsgOp], *, recall: bool=False):
        from plugins.admin import AdminAchv
        from plugins.live import LiveAchv
        
        # print('[check_avaliable]')
        for e in (AdminAchv.ADMIN, LiveAchv.CAPTAIN):
            if await self.achv.is_used(e):
                return True

        # print('[check_achvs]')
        # 需要至少一个稀有成就
        obtained_achvs = await self.achv.get_obtained()
        obtained_rare_achvs = self.achv.filter_by_min_rarity(obtained_achvs, AchvRarity.RARE)
        if len(obtained_rare_achvs) < 2:
            raise RuntimeError('需要至少持有两枚稀有级及以上成就')

        grouped = self.achv.group_by_rarity(obtained_achvs)
        achv_cnts = {k: len(v) for k, v in grouped.items()}

        speedup = 0

        # print(f'{achv_cnts=}')

        for k, v in achv_cnts.items():
            if k in self.SPEEDUP_LOOKUP:
                speedup += self.SPEEDUP_LOOKUP[k] * v

        if man is None: return True

        # print(f'{speedup=}, {man.get_effective_speech_cnt()=}')
        speedup += self.SPEEDUP_EFFECTIVE_SPEECH * man.get_effective_speech_cnt()
        
        cooldown_duration = max(self.MIN_COOLDOWN_DURATION, self.MAX_COOLDOWN_DURATION - speedup)

        cooldown_reamins = man.get_cooldown_remains(cooldown_duration)

        # print(f'[check_cooldown_reamins], {cooldown_reamins=}, {cooldown_duration=}, {speedup=}')
        if cooldown_reamins > 0:
            if cooldown_reamins < 60:
                await self.achv.submit(AiExtAchv.EDGE)
            print(f'{msg_op=}, {recall=}')
            if msg_op is not None and recall:
                await member_op.send_temp([
                    f'AI功能冷却中, 请{get_delta_time_str(cooldown_reamins, use_seconds=False)}后再试, 多多发言可以大幅减少冷却时间哦'
                ])
                self.admin.mark_recall_protected(msg_op.msg.id)
                await msg_op.recall()
            # raise RuntimeError(f'冷却中, 请{get_delta_time_str(cooldown_reamins, use_seconds=False)}后再试, 多多发言可以大幅减少冷却时间哦')
            return False
        
        return True

    def flatten(self, r: list, f: list = None):
        if f is None:
            f = []
        for e in r:
            if isinstance(e, list):
                self.flatten(e, f)
            else:
                f.append(e)
        return f

    def breakdown_r(self, root: list):
        root = [s for s in root if not isinstance(s, str) or len(s) > 2]

        if len(root) >= self.MAX_BREAKDOWN:
            return root
        
        str_len = [len(s) if isinstance(s, str) else 0 for s in root]
        if len(str_len) == 0:
            return root
        
        index_max = max(range(len(str_len)), key=str_len.__getitem__)
        
        len_max = str_len[index_max]
        breakdown_prob = (len_max - self.MIN_BREAKDOWN_PROB_WORDS) / (self.MAX_BREAKDOWN_PROB_WORDS - self.MIN_BREAKDOWN_PROB_WORDS)
        will_breakdown = random.random() < breakdown_prob

        if not will_breakdown: return root

        txt: str = root[index_max]

        for rexpr in [r'\n+', r'(?<=!|！|。)', r'(?<=~)', r',|，']:
            splited_by = re.split(rexpr, txt)
            striped = [t.strip() for t in splited_by]
            filtered = [t for t in striped if len(t) > 0]
            if len(filtered) > 1 and len(root) - 1 + len(filtered) <= self.MAX_BREAKDOWN:
                root[index_max] = filtered
                root = self.flatten(root)
                return self.breakdown_r(root)
            
        return root

    @delegate(InstrAttr.BACKGROUND)
    async def as_chat_seq(self, op: SourceOp, *, mc: list):
        # 咱也一样... 不过没关系，咱可以攒着下次用嘛~ 下次就能用闪电五连鞭连抽五次啦！
        root = self.breakdown_r(mc)
        
        for i, e in enumerate(root):
            if i != 0:
                if isinstance(e, str):
                    prev_e = e
                    e = re.sub(r'(^[\s，,。]+)|([\s]+$)', '', e)

                    if len(e) == 0:
                        continue

                    await asyncio.sleep(min(0.2 + len(e) / 7, 3))

                    if len(prev_e) != len(e):
                        await asyncio.sleep(1)
                else:
                    await asyncio.sleep(1 + random.random())
            resp = await op.send([e])
            # resp = await self.bot.send_group_message(group_id, [e])
            self.ai_resp_msg_ids.append(resp.message_id)
    
    def is_chat_seq_msg(self, msg_id: int):
        return msg_id in self.ai_resp_msg_ids

    @delegate(InstrAttr.FORECE_BACKUP)
    async def mark_invoked(self, man: ThrottleMan, member: GroupMember):
        
        man.mark_invoked()
        await self.achv.submit(AiExtAchv.AI_COOLDOWN, silent=True)

    @any_instr()
    async def update_cd_state(self):
        try:
            if await self.check_avaliable():
                await self.achv.remove(AiExtAchv.AI_COOLDOWN, force=True)
        except: ...
    