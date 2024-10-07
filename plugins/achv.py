from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, EnumMeta
import inspect
from itertools import groupby
import sys
import time
from typing import Dict, Optional, Union
from mirai import At
from plugin import AchvCustomizer, Inject, InjectNotifier, InstrAttr, Plugin, any_instr, card_changed_instr, delegate, top_instr, route, enable_backup
from utilities import AchvEnum, AchvInfo, AchvRarity, AchvRarityVal, AdminType, GroupLocalStorage, GroupOp, breakdown_chain_sync, get_logger
from regex_emoji import EMOJI_REGEXP, EMOJI_SEQUENCE
import typing
from mirai.models.entities import GroupMember, MemberInfoModel
from mirai.models.events import MemberCardChangeEvent

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from plugins.renderer import Renderer
    from plugins.admin import Admin

logger = get_logger()

@dataclass
class AchvExtra():
    create_ts: float = field(default_factory=time.time)
    obtained_cnt: int = field(default=1)
    obtained_ts: Union[None, float] = field(default=None)

@dataclass
class Ranked():
    rank: int
    val: str

@dataclass
class CollectedAchvMan():
    achvs: Dict[Enum, AchvExtra] = field(default_factory=dict)
    _using: Enum = None
    last_using_ts: int = 0

    def has(self, e: AchvEnum):
        if e is None: return False
        info = typing.cast(AchvInfo, e.value)
        return e in self.achvs and info.opts.target_obtained_cnt > 0 and self.achvs[e].obtained_cnt >= info.opts.target_obtained_cnt
    
    def get_achv_extra(self, e: AchvEnum):
        if not self.has(e): return None
        return self.achvs[e]
    
    def get_used_achv(self):
        if self._using is None:
            return None
        if self.has(self._using):
            return self._using
        return None
    
    def get_obtained(self, *, include_hidden: bool=False):
        return [achv_enum for achv_enum in self.achvs.keys() if self.has(achv_enum) and (not (achv := typing.cast(AchvInfo, achv_enum.value)).opts.hidden or include_hidden)]

    @property
    def using(self):
        return self.get_used_achv()
    
    @using.setter
    def using(self, val: Union[None, Enum]):
        if self._using is not None:
            info: AchvInfo = self._using.value
            if info.opts.min_display_durtion is not None and time.time() - self.last_using_ts <= info.opts.min_display_durtion:
                raise RuntimeError(f'目前还不能卸下称号"{info.get_display_text()}"')
                ...
        self.last_using_ts = time.time()
        self._using = val

#使用方式：插件注入Achv、并且插件同文件下存在从AchvEnum继承的枚举

@route('成就系统')
@enable_backup
class Achv(Plugin, InjectNotifier):
    gls: GroupLocalStorage[CollectedAchvMan] = GroupLocalStorage[CollectedAchvMan]()

    renderer: Inject['Renderer']
    admin: Inject['Admin']

    def __init__(self):
        self.registed_achv: Dict[Plugin, EnumMeta] = {}

    def register(self, plugin: Plugin, em: EnumMeta):
        if plugin in self.registed_achv: return
        logger.debug(f'add {em.__name__} from {plugin.__class__.__name__}')
        self.registed_achv[plugin] = em

    def injected(self, target: Plugin):
        if target in self.registed_achv: return
        mod = sys.modules[target.__module__]
        for _, member in inspect.getmembers(mod, lambda m: inspect.isclass(m) and m.__module__ == mod.__name__):
            if issubclass(member, AchvEnum):
                self.register(target, member)
        ...

    def get_registed_achvs(self):
        return list(self.registed_achv.values())

    @delegate()
    async def is_deletable(self, e: AchvEnum, man: Optional[CollectedAchvMan]):
        info = typing.cast(AchvInfo, e.value)

        if not man.has(e):
            return False
        
        ts = await self.get_achv_obtained_ts(e)

        if info.opts.locked:
            return False

        if info.opts.dynamic_deletable:
            p: AchvCustomizer = next((k for k, v in self.registed_achv.items() if v is e.__class__))
            res = await p.is_achv_deletable(e)
            if res is None:
                res = False
            return res
        
        if info.opts.is_punish:
            span = datetime.now().replace(tzinfo=None) - datetime.fromtimestamp(ts).replace(tzinfo=None)
            if span.days < 3:
                return False
        
        return True

        ...

    @delegate()
    async def remove(self, e: AchvEnum, man: Optional[CollectedAchvMan], *, force: bool=False):
        if man is None:
            return None

        info = typing.cast(AchvInfo, e.value)

        if e in man.achvs:
            has_achv = man.has(e)

            if not await self.is_deletable(e) and not force:
                raise RuntimeError(f'目前还不能撤销{info.aka}')

            man.achvs.pop(e)
            self.backup_man.trigger_backup()
            await self.update_member_name()
            return has_achv
        
        return None
    
    @delegate(InstrAttr.FORECE_BACKUP)
    async def batch_submit(self, e: AchvEnum, op: GroupOp, *, member_ids: Iterable[int], override_obtain_cnt: int = None, silent: bool = False):
        
        async def ctx_submit(member_id: int):
            member = await op.get_member(member_id)
            async with self.override(member):
                return await self.submit(e, override_obtain_cnt=override_obtain_cnt, silent=True)

        res = [(await ctx_submit(member_id), member_id) for member_id in member_ids]

        filtered_res_ids = [id for b, id in res if b]

        if not silent and len(filtered_res_ids) > 0:
            info = typing.cast(AchvInfo, e.value)

            if info.opts.custom_obtain_msg is not None:
                msg = ['[新成就] ', *[At(target=member_id) for member_id in filtered_res_ids], f' {info.opts.custom_obtain_msg}']
            else:
                msg = ['[新成就]恭喜 ', *[At(target=member_id) for member_id in filtered_res_ids], f' 获得成就: {info}']
            try: 
                await op.send(msg)
            except: ...

        return [b for b, _ in res]

    @delegate(InstrAttr.FORECE_BACKUP)
    async def submit(self, e: AchvEnum, member: GroupMember, op: GroupOp, man: CollectedAchvMan, *, override_obtain_cnt: int = None, silent: bool = False):
        info = typing.cast(AchvInfo, e.value)
        prev_obtained_cnt = 0

        if e in man.achvs:
            prev_obtained_cnt = man.achvs[e].obtained_cnt
            man.achvs[e].obtained_cnt += 1
        else:
            man.achvs[e] = AchvExtra()

        if override_obtain_cnt is not None:
            man.achvs[e].obtained_cnt = override_obtain_cnt

        if not (prev_obtained_cnt < info.opts.target_obtained_cnt and man.achvs[e].obtained_cnt >= info.opts.target_obtained_cnt):
            return False
        
        man.achvs[e].obtained_ts = time.time()
        
        if not silent:
            if info.opts.custom_obtain_msg is not None:
                msg = ['[新成就] ', At(target=member.id), f' {info.opts.custom_obtain_msg}']
            else:
                msg = ['[新成就]恭喜 ', At(target=member.id), f' 获得成就: {info}']
            try: 
                await op.send(msg)
            except: ...

        await self.update_member_name()
        return True
    
    @delegate()
    async def get_obtained(self, man: Optional[CollectedAchvMan], *, include_hidden: bool=False):
        if man is None: return []
        obtained_achvs = man.get_obtained(include_hidden=include_hidden)
        for p, em in self.registed_achv.items():
            if not isinstance(p, AchvCustomizer): continue
            for e in em:
                e: AchvEnum
                info: AchvInfo = e.value
                if not include_hidden and info.opts.hidden: continue
                if not info.opts.dynamic_obtained: continue
                if await p.is_achv_obtained(e):
                    obtained_achvs.append(e)
        return obtained_achvs
    
    def group_by_rarity(self, achvs: list[AchvEnum]):
        def comp(it: AchvEnum):
            info: AchvInfo = it.value
            return typing.cast(AchvRarityVal, info.opts.rarity.value).level

        sorted_achvs: list[AchvEnum] = sorted(achvs, key=comp)
        grouped = groupby(sorted_achvs, lambda it: it.opts.rarity)

        return {k: list(v) for k, v in grouped}

    def filter_by_min_rarity(self, achvs: list[AchvEnum], min_rarity: AchvRarity):
        return [a for a in achvs if typing.cast(AchvInfo, a.value).opts.rarity.value.level >= min_rarity.value.level]
        ...

    @delegate()
    async def has(self, e: AchvEnum, man: Optional[CollectedAchvMan]):
        if man is None: return False
        return man.has(e)
    
    @delegate()
    async def get_achv_obtained_ts(self, e:AchvEnum, man: Optional[CollectedAchvMan]):
        extra = man.get_achv_extra(e)
        if extra is None: 
            return None
        if extra.obtained_ts is None: 
            return extra.create_ts
        return extra.obtained_ts

    @delegate()
    async def get_achv_collected_count(self, e:AchvEnum, man: Optional[CollectedAchvMan]):
        extra = man.get_achv_extra(e)
        if extra is None: 
            return 0
        return extra.obtained_cnt
    
    @delegate()
    async def aka_to_achv(self, aka: str):
        for meta in self.registed_achv.values():
            e = next((e for e in meta if typing.cast(AchvInfo, e.value).aka == aka), None)
            if e is not None:
                return e
        else:
            raise RuntimeError(f'不存在名叫"{aka}"的成就')
    
    @delegate()
    async def get_used(self, man: Optional[CollectedAchvMan]):
        if man is None:
            return None
        
        return man.get_used_achv()
        ...
    
    @delegate()
    async def is_used(self, e: AchvEnum, man: Optional[CollectedAchvMan]):
        if man is None: return False
        return man.using is e

    @top_instr('所有成就')
    async def all_achv(self):
        s = []
        for p, meta in self.registed_achv.items():
            s.append(f'{p.get_config().name}:')
            s.extend((str(e.value) for e in meta))
        return '\n'.join(s)

    # @admin
    # @top_instr('summary')
    # async def summary(self, glse_: gls.event_t()):
    #     glse = typing.cast(GroupLocalStorageAsEvent[CollectedAchvMan], glse_)

    #     print('running...')

    #     mans = glse.get_data_of_group()

    #     dd: dict[AchvRarity, int] = {}

    #     for man in mans.values():
            
    #         for e in [typing.cast(AchvEnum, e) for e in man.achvs if man.has(e)]:
    #             info = typing.cast(AchvInfo, e.value)
    #             rarity = info.opts.rarity
    #             if rarity not in dd:
    #                 dd[rarity] = 0
    #             else:
    #                 dd[rarity] += 1

    #     print(dd)
        
    #     return '\n'.join(['统计数据', *[f'{k.value.aka}: {v}' for k, v in dd.items()]])

    @top_instr('赋予')
    async def award(self, at: At, aka: str):
        async with self.admin.privilege(type=AdminType.SUPER):
            for meta in self.registed_achv.values():
                e = next((e for e in meta if typing.cast(AchvInfo, e.value).aka == aka), None)
                if e is not None:
                    break
            else:
                return f'不存在名叫"{aka}"的成就'
            
            member = await self.member_from(at=at)
            async with self.override(member):
                await self.submit(e)

    @top_instr('撤销')
    async def remove_cmd(self, at: At, aka: str, force_arg: Optional[str]):
        async with self.admin.privilege(type=AdminType.SUPER):
            for meta in self.registed_achv.values():
                e = next((e for e in meta if typing.cast(AchvInfo, e.value).aka == aka), None)
                if e is not None:
                    break
            else:
                return f'不存在名叫"{aka}"的成就'
            
            force = force_arg == '强制'

            member = await self.member_from(at=at)
            async with self.override(member):
                result = await self.remove(e, force=force)

                if result is None:
                    return '撤销失败, 未获得成就进度'
                
                if result:
                    return [f'为', at, f' 撤销了{aka}...']
                
                if not result:
                    return [f'为', at, f' 清空了{aka}的进度...']

    

    @top_instr('成就')
    async def disp_achv(self, man: Optional[CollectedAchvMan]):
        if man is None or len(man.achvs) == 0:
            return '尚未获得任何成就'
        
        achvs = []

        for achv_enum, extra in man.achvs.items():
            info = typing.cast(AchvInfo, achv_enum.value)
            if info.opts.hidden: continue
            obtained_ts = await self.get_achv_obtained_ts(achv_enum)
            item = {
                'aka': info.aka,
                'obtained_ts': obtained_ts,
                'target_obtained_cnt': info.opts.target_obtained_cnt,
                'obtained_cnt': extra.obtained_cnt,
                'opts': {
                    'rarity': info.opts.rarity.name,
                    'is_punish': info.opts.is_punish,
                    'emoji_display': info.get_display_text() if EMOJI_REGEXP.fullmatch(info.get_display_text()) else None
                },
                'is_eligible': await self.is_deletable(achv_enum) and info.opts.rarity.value.level >= AchvRarity.UNCOMMON.value.level,
            }
            achvs.append(item)

        await self.renderer.render_as_task(url='member-achvs', data={
            'name': await self.get_raw_member_name(),
            'achvs': achvs
        })
    
    @top_instr('进度')
    async def achv_progress(self, aka: str, man: Optional[CollectedAchvMan]):
        for meta in self.registed_achv.values():
            if next((val for e in meta if (val := typing.cast(AchvInfo, e.value)).aka == aka), None) is not None:
                break
        else:
            return f'不存在名叫"{aka}"的成就'
        
        if man is None or len(man.achvs) == 0:
            return f'尚未开始成就"{aka}"的获取进度'
        
        e = next((k for k in man.achvs.keys() if aka == typing.cast(AchvInfo, k.value).aka), None)
        if e is None:
            return f'尚未开始成就"{aka}"的获取进度'
        
        if man.has(e):
            return f'已获得成就"{aka}"'

        extra = man.achvs[e]
        
        info = typing.cast(AchvInfo, e.value)

        return f'{info}: {extra.obtained_cnt}/{info.opts.formatted_target_obtained_cnt}{info.opts.unit}'


    @top_instr('佩戴')
    async def use_achv(self, aka: str, man: Optional[CollectedAchvMan]):
        for meta in self.registed_achv.values():
            if next((val for e in meta if (val := typing.cast(AchvInfo, e.value)).aka == aka), None) is not None:
                break
        else:
            return f'不存在名叫"{aka}"的成就'
        
        if man is None or len(man.achvs) == 0:
            return f'尚未获得成就"{aka}"'

        e = next((k for k in man.achvs.keys() if aka == typing.cast(AchvInfo, k.value).aka), None)
        if not man.has(e):
            return f'尚未获得成就"{aka}"'
        
        self.backup_man.set_dirty()
        man.using = e

        await self.update_member_name()
        # return '佩戴成功'
    
    @top_instr('取消佩戴')
    async def drop_achv(self, man: Optional[CollectedAchvMan]):
        if man is None:
            return '当前没有佩戴任何成就'

        used_achv =  man.get_used_achv()
        if used_achv is None:
            return '当前没有佩戴任何成就'
        
        self.backup_man.set_dirty()
        man.using = None

        await self.update_member_name()
        info = typing.cast(AchvInfo, used_achv.value)
        # return f'卸下了成就"{info.aka}"'

    # 群名片改动
    # 群头衔改动
            
    # unicode 不可见字符
    # https://zh.wikipedia.org/wiki/Unicode%E6%8E%A7%E5%88%B6%E5%AD%97%E7%AC%A6
            
    @card_changed_instr()
    async def on_card_changed(self, event: MemberCardChangeEvent):
        logger.debug(f'card_changed_instr, {event=}')
        ...

    @delegate()
    async def update_member_name(self, member: GroupMember, man: Optional[CollectedAchvMan]):
        weared_achv_info_kv: dict[str, AchvInfo] = {}

        if man is not None:
            for e in await self.get_obtained(include_hidden=True):
                info = typing.cast(AchvInfo, e.value)
                if info.opts.display_pinned:
                    weared_achv_info_kv[info.get_display_text()] = info

            used_achv = man.get_used_achv()
            if used_achv is not None:
                info = typing.cast(AchvInfo, used_achv.value)
                weared_achv_info_kv[info.get_display_text()] = info

        def display_weight_or_default(info: AchvInfo, _def: int):
            return display_weight if (display_weight := info.opts.display_weight) is not None else _def

        def achv_op(s: str, ctx):
            if s in weared_achv_info_kv:
                info = weared_achv_info_kv.pop(s)
                return Ranked(val=f'[{s}]', rank=display_weight_or_default(info, 0))
            
        def emoji_op(s: str, ctx):
            # print(f'emoji, {s}')
            if s in weared_achv_info_kv:
                info = weared_achv_info_kv.pop(s)
                return Ranked(val=s, rank=display_weight_or_default(info, 1))

        li = member.member_name

        # 删除掉在中括号中的emoji符号
        li = breakdown_chain_sync(li, rf"\[({EMOJI_SEQUENCE})\]", lambda s, ctx: None)

        # 删除掉不在成就中的emoji符号, 并且标记他们
        li = breakdown_chain_sync(li, rf"({EMOJI_SEQUENCE})", emoji_op)

        # [r'\[(.*?)\]', r'【(.*?)】', r'\((.*?)\)', r'（(.*?)）', r'{(.*?)}', r'"(.*?)"', r'\'(.*?)\'', r'“(.*?)”']
        for r in [r'\[(.*?)\]', r'【(.*?)】', r'\((.*?)\)', r'（(.*?)）']:
            li = breakdown_chain_sync(li, r, achv_op)

        # 将新的称号整合到群名中
        def wrap_display_text(display_name: str, info: AchvInfo):
            if EMOJI_REGEXP.fullmatch(display_name):
                return Ranked(val=display_name, rank=display_weight_or_default(info, 1))
            else:
                return Ranked(val=f'[{display_name}]', rank=display_weight_or_default(info, 0))

        li = [*[wrap_display_text(*item) for item in weared_achv_info_kv.items()], *li]

        li = [i if isinstance(i, Ranked) else Ranked(rank=0, val=i) for i in li]

        # TODO: 将emoji排序放在开头
        def sort_ranked(s: Ranked):
            return s.rank
            ...
        li_sorted = sorted(li, key=sort_ranked, reverse=True)
        # print(f'{li=}, {li_sorted=}')

        new_name = ''.join([i.val for i in li_sorted])

        if new_name != member.member_name:
            logger.info(f'cname {member.member_name} -> {new_name}')
            await self.bot.member_info().set(member.group.id, member.id, MemberInfoModel(
                name=new_name
            ))

    @delegate()
    async def get_raw_member_name(self, member: GroupMember):
        li = member.member_name

        # 删除掉在中括号中的emoji符号
        li = breakdown_chain_sync(li, rf"\[({EMOJI_SEQUENCE})\]", lambda s, ctx: None)

        # 删除掉不在成就中的emoji符号, 并且标记他们
        li = breakdown_chain_sync(li, rf"({EMOJI_SEQUENCE})", lambda s, ctx: None)

        for r in [r'\[(.*?)\]', r'【(.*?)】', r'\((.*?)\)', r'（(.*?)）']:
            li = breakdown_chain_sync(li, r, lambda s, ctx: None)
        
        return ''.join(li)

    @any_instr()
    async def assign_name(self):
        await self.update_member_name()
