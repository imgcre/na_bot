import asyncio
from dataclasses import dataclass
import random
import re
from typing import Final,  Optional
from event_types import EffectiveSpeechEvent
from mirai import At, GroupMessage, MessageEvent, Plain
from plugin import Plugin, any_instr, delegate, InstrAttr, route, enable_backup, Inject
from mirai.models.entities import GroupMember

from typing import TYPE_CHECKING

from utilities import AchvRarity, AchvOpts, GroupLocalStorage, GroupMemberOp, MsgOp, SourceOp, get_delta_time_str, AchvEnum, handler, throttle_config
if TYPE_CHECKING:
    from plugins.achv import Achv
    from plugins.events import Events
    from plugins.gpt import Gpt
    from plugins.admin import Admin
    from plugins.throttle import Throttle

class AiExtAchv(AchvEnum):
    AI_COOLDOWN = 0, 'AI冷却中', '主动和bot对话功能在冷却状态下时自动获得', AchvOpts(display_pinned=True, locked=True, hidden=True, display='🆒', display_weight=-1)
    EDGE = 1, '边缘', '在AI的CD只有一分钟时发起对话获得', AchvOpts(rarity=AchvRarity.UNCOMMON, display='⌛', custom_obtain_msg='差点就……')

@dataclass
class CustomMan():
    affection: int = 50

@route('AI拓展')
@enable_backup
class AiExt(Plugin):
    gls_custom: GroupLocalStorage[CustomMan] = GroupLocalStorage[CustomMan]()

    achv: Inject['Achv']
    events: Inject['Events']
    gpt: Inject['Gpt']
    admin: Inject['Admin']
    throttle: Inject['Throttle']

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

    @throttle_config(name='AI', achv_speedup=True, effective_speedup=True, enable_min_duration=True)
    async def check_avaliable(self, *, recall: bool=False):
        cooldown_reamins = await self.throttle.get_cooldown_reamins()
        use_min_duration = await self.throttle.is_use_min_duration()
        if recall and not not use_min_duration and cooldown_reamins > 0 and cooldown_reamins < 60:
            await self.achv.submit(AiExtAchv.EDGE)
        return await self.throttle.do(recall=recall, cooldown_reamins=cooldown_reamins)

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

    async def mark_invoked(self):
        await self.throttle.reset(fn=self.check_avaliable)
        await self.achv.submit(AiExtAchv.AI_COOLDOWN, silent=True)

    @any_instr()
    async def update_cd_state(self):
        try:
            cooldown_reamins = await self.throttle.get_cooldown_reamins(fn=self.check_avaliable)
            if cooldown_reamins <= 0:
                await self.achv.remove(AiExtAchv.AI_COOLDOWN, force=True)
        except: ...

    @delegate()
    async def get_affection(self, man: CustomMan):
        return man.affection

    @delegate()
    async def increase_affection(self, man: CustomMan):
        await self.set_affection(val=man.affection + 1, text='提升')
    
    @delegate()
    async def decrease_affection(self, man: CustomMan):
        await self.set_affection(val=man.affection - 1, text='降低')

    @delegate()
    async def set_affection(self, source_op: Optional[SourceOp], event: MessageEvent, man: CustomMan, *, val: int, text: str):
        for c in event.message_chain:
            if isinstance(c, Plain):
                if '好感' in c.text:
                    return
        try:
            if source_op is not None:
                man.affection = val
                self.backup_man.set_dirty()
                await source_op.send(['对', At(target=source_op.member.id), f' 的好感度${text}了!'])
        except: ...