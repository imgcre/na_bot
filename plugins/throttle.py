from dataclasses import dataclass, field
import gc
import inspect
import time
import traceback
from typing import Callable, TYPE_CHECKING, Final, Optional
from plugin import Inject, InstrAttr, Plugin, delegate, enable_backup, route
from mirai.models.entities import GroupMember
from utilities import AchvRarity, GroupLocalStorage, GroupMemberOp, MsgOp, ThrottleConfig, ensure_attr, get_delta_time_str, is_nested, to_unbind

if TYPE_CHECKING:
    from plugins.achv import Achv
    from plugins.admin import Admin

@dataclass
class FnThrottleInfo():
    effective_speech_cnt_snapshot: int
    created_ts: float = field(default_factory=time.time)
    do_ts: float = 0
    try_cnt: int = 0

    def update(self):
        self.do_ts = time.time()
        self.try_cnt += 1

@dataclass
class ThrottleMan():
    fn_infos: dict[str, FnThrottleInfo] = field(default_factory=dict)

@route('限流')
@enable_backup
class Throttle(Plugin):
    gls_throttle: GroupLocalStorage[ThrottleMan] = GroupLocalStorage[ThrottleMan]()

    achv: Inject['Achv']
    admin: Inject['Admin']

    SPEEDUP_LOOKUP: Final = {
        AchvRarity.COMMOM: 30 * 60,
        AchvRarity.UNCOMMON: 10 * 60,
        AchvRarity.RARE: 5 * 60,
        AchvRarity.EPIC: 2 * 60,
    }

    MIN_DO_DURATION_THRESHOLD: Final = 60
    MAX_TRY_CNT: Final = 5
    SPEEDUP_EFFECTIVE_SPEECH: Final = 10 * 60
    MAX_COOLDOWN_DURATION: Final = 6 * 60 * 60
    MIN_COOLDOWN_DURATION: Final = 5 * 60

    @delegate()
    async def get_cooldown_reamins(self, man: ThrottleMan, *, fn: Callable=None):
        from plugins.meow import MeowAchv

        if fn is None:
            fn = self._get_caller_fn()
        else:
            fn = to_unbind(fn)

        if fn.__qualname__ not in man.fn_infos:
            return 0
        fn_info = man.fn_infos[fn.__qualname__]

        use_min_duration = await self.is_use_min_duration(fn=fn)
            
        speedup = 0

        config = ensure_attr(fn, ThrottleConfig)

        max_cooldown_duration = self.MAX_COOLDOWN_DURATION
        if config.max_cooldown_duration is not None:
            max_cooldown_duration = config.max_cooldown_duration

        if config.achv_speedup:
            obtained_achvs = await self.achv.get_obtained()
            grouped = self.achv.group_by_rarity(obtained_achvs)
            achv_cnts = {k: len(v) for k, v in grouped.items()}

            for k, v in achv_cnts.items():
                if k in self.SPEEDUP_LOOKUP:
                    speedup += self.SPEEDUP_LOOKUP[k] * v

        if config.effective_speedup:
            effective_speech_cnt = await self.achv.get_achv_collected_count(MeowAchv.CACTUS)
            speedup += self.SPEEDUP_EFFECTIVE_SPEECH * max(effective_speech_cnt - fn_info.effective_speech_cnt_snapshot, 0)

        cooldown_duration = max_cooldown_duration - speedup
        if cooldown_duration < self.MIN_COOLDOWN_DURATION or use_min_duration:
            cooldown_duration = self.MIN_COOLDOWN_DURATION
        return fn_info.created_ts + cooldown_duration - time.time()

    @delegate()
    async def do(self, man: ThrottleMan, member_op: GroupMemberOp, msg_op: Optional[MsgOp], 
        *, recall: bool=True, cooldown_reamins: Optional[float]=None, fn: Callable=None
    ):
        if fn is None:
            fn = self._get_caller_fn()
        else:
            fn = to_unbind(fn)

        if fn.__qualname__ not in man.fn_infos:
            return True
        fn_info = man.fn_infos[fn.__qualname__]

        if cooldown_reamins is None:
            cooldown_reamins = await self.get_cooldown_reamins(fn=fn)

        if cooldown_reamins <= 0:
            return True
        
        config = ensure_attr(fn, ThrottleConfig)

        try:
            if (
                time.time() - fn_info.do_ts < self.MIN_DO_DURATION_THRESHOLD
                or fn_info.try_cnt >= self.MAX_TRY_CNT - 1
            ):
                reason = f'使用{config.name}功能过于频繁'
                await self.admin.inc_violation_cnt(reason=reason, hint=reason)
            if msg_op is not None and recall:
                text = [
                    f'{config.name}功能冷却中, 请{get_delta_time_str(cooldown_reamins, use_seconds=False)}后再试'
                ]
                if config.effective_speedup:
                    text.append('多多发言可以大幅减少冷却时间哦')
                await member_op.send_temp([
                    ', '.join(text)
                ])
                self.admin.mark_recall_protected(msg_op.msg.id)
                await msg_op.recall()
        finally:
            fn_info.update()
            self.backup_man.set_dirty()

        return False

    @delegate(InstrAttr.FORECE_BACKUP)
    async def reset(self, man: ThrottleMan, *, fn: Callable=None):
        from plugins.meow import MeowAchv

        if fn is None:
            fn = self._get_caller_fn()
        else:
            fn = to_unbind(fn)

        man.fn_infos[fn.__qualname__] = FnThrottleInfo(
            effective_speech_cnt_snapshot=await self.achv.get_achv_collected_count(MeowAchv.CACTUS),
        )

    def _get_caller_fn(self):
        i = 2
        while True:
            target_caller = self._get_caller_fn_internal(depth=i)
            i += 1
            if not is_nested(target_caller):
                break
        return target_caller
    
    def _get_caller_fn_internal(self, *, depth: int=0):
        frm = inspect.stack()[1+depth][0]

        code_obj = frm.f_code
        return [
            obj for obj in gc.get_referrers(code_obj) 
            if hasattr(obj, '__code__') and obj.__code__ is code_obj
        ][0]
    
    async def is_use_min_duration(self, *, fn: Callable=None):
        from plugins.admin import AdminAchv
        from plugins.live import LiveAchv

        if fn is None:
            fn = self._get_caller_fn()
        else:
            fn = to_unbind(fn)

        config = ensure_attr(fn, ThrottleConfig)

        if not config.enable_min_duration:
            return False

        for e in (AdminAchv.ADMIN, LiveAchv.CAPTAIN):
            if await self.achv.is_used(e):
                return True
        return False
