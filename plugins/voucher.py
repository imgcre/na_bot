from dataclasses import dataclass, field
import time
from typing import Final, Optional
import typing
from decimal import Decimal

from mirai import At, Image
from mirai.models.entities import GroupMember, MemberInfoModel

from plugin import Inject, Plugin, delegate, enable_backup, top_instr, any_instr, InstrAttr, route
import random
import random
from itertools import groupby

from utilities import AchvEnum, AchvInfo, AchvOpts, AchvRarity, AchvRarityVal, Upgraded, User, UserSpec

class VoucherAchv(AchvEnum):
    AFRICAN_CHIEFS = 0, '非酋', '连续10次抽奖都未成功', AchvOpts(rarity=AchvRarity.LEGEND, display='🧔🏿', custom_obtain_msg='成为了反方向的欧皇', target_obtained_cnt=10)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from plugins.achv import Achv
    from plugins.fur import Fur

@dataclass
class DrawResult():
    consumed_achv: AchvEnum
    suceeed: bool
    create_ts: float = field(default_factory=time.time)

@dataclass
class ConsumeRecord():
    id: float
    count: Decimal
    create_ts: float = field(default_factory=time.time)

@dataclass
class GiftRecord():
    consume_id: float
    count: Decimal
    create_ts: float = field(default_factory=time.time)
    ...

@dataclass
class UserVoucherMan(Upgraded):
    results: list[DrawResult] = field(default_factory=list)
    consumes: list[ConsumeRecord] = field(default_factory=list)
    gifts: list[GiftRecord] = field(default_factory=list)
    in_flow: bool = False
    count: Decimal = 0

    def append_result(self, res: DrawResult):
        self.results.append(res)
        if res.suceeed:
            self.count += 1

    def append_consume(self, cnt: Decimal):
        while True:
            n_float = random.random()
            same_id_item = next((r.id for r in self.consumes if r.id == n_float), None)
            if same_id_item is not None:
                continue
            self.consumes.append(ConsumeRecord(id=n_float, count=cnt))
            self.count -= cnt
            return n_float
        
    def append_gift(self, rec: GiftRecord):
        self.results.append(rec)
        self.count += rec.count

    def is_satisfied(self, cnt: Decimal):
        return self.count >= cnt
    
    def get_count(self):
        return self.count

    
# class BarchiRewardCategories(RewardCategoryEnum):
#     _ = 0, '吧唧'

# class Barchis(RewardEnum):
#     ALL_OF_YARN = 0, '毛线球', RewardOpts(category=BarchiRewardCategories._)



# 类别的is_exclusive为True的话, RewardOpts的max_claims将强制为1
    
# class RewardCategories(Enum):
#     Barchi = '吧唧', RewardCategoryOpts(is_exclusive=True)
#     ...

# class Barchis(Enum):
#     ALL_OF_YARN = '毛线球', RewardOpts(category=RewardCategories.Barchi, max_claims=1, ticket_cost=1)
#     WALLOW = '打滚'
#     PALM_TREASURE = '掌中宝'
#     ELIZABETHAN_COLLAR = '伊丽莎白圈'
#     PASSION_FRUIT = '百香果'

@route('兑奖券系统')
@enable_backup
class Voucher(Plugin):
    user_sweepstakes: UserSpec[UserVoucherMan] = UserSpec[UserVoucherMan]()

    achv: Inject['Achv']
    fur: Inject['Fur']

    PROBS: Final = {
        AchvRarity.UNCOMMON: 0.1,
        AchvRarity.RARE: 0.3,
        AchvRarity.EPIC: 0.7,
        AchvRarity.LEGEND: 0.99,
    }

    MAG_PUNISHMENT: Final = 0.01 # 惩罚倍率

    @delegate()
    async def is_satisfied(self, user: User, *, cnt: Decimal):
        man = self.user_sweepstakes.get_data(user.id)
        if man is None:
            return False
        return man.is_satisfied(cnt)
    
    @delegate()
    async def consume(self, user: User, *, cnt: Decimal, force: bool=False):
        if not force and not await self.is_satisfied(cnt=cnt):
            raise RuntimeError('兑奖券不足')
        
        self.backup_man.set_dirty()
        man = self.user_sweepstakes.get_or_create_data(user.id)
        return man.append_consume(cnt)

    # 输出文本, 退出持续模式
    @delegate(InstrAttr.FORECE_BACKUP)
    async def draw(self, aka: str, man: UserVoucherMan):

        try:
            ac: AchvEnum = await self.achv.aka_to_achv(aka)
        except Exception as e:
            try:
                return await self.fur.get_pic(aka), True
            except:
                raise e
     
        ac_info = typing.cast(AchvInfo, ac.value)
        rarity = ac_info.opts.rarity
        if rarity not in self.PROBS:
            return f'成就{ac_info.aka}不可参与该活动', False
        
        has_ac = await self.achv.has(ac)
        if not has_ac:
            return f'尚未获得成就{ac_info.aka}', False
        
        prob = self.PROBS[rarity]
 
        if ac_info.opts.is_punish:
            prob *= self.MAG_PUNISHMENT

        val = random.random()

        outputs = []

        await self.achv.remove(ac)
        outputs.append(f'消耗了{ac_info.aka}...')

        outputs.append(f'将以{prob * 100:.1f}%的概率进行抽奖...')
        outputs.append(f'投掷得到了数值: {val:.3f}...')

        if val > prob:
            man.append_result(DrawResult(consumed_achv=ac, suceeed=False))
            outputs.append(f'失败, 未获得奖励')
            await self.achv.submit(VoucherAchv.AFRICAN_CHIEFS)
            return '\n'.join(outputs), False

        man.append_result(DrawResult(consumed_achv=ac, suceeed=True))
        outputs.append(f'成功获得了兑奖券*1')
        if not await self.achv.has(VoucherAchv.AFRICAN_CHIEFS):
            await self.achv.remove(VoucherAchv.AFRICAN_CHIEFS, force=True)
        return '\n'.join(outputs), True

    @any_instr()
    async def in_flow_draw_cmd(self, aka: str, man: UserVoucherMan):
        if not man.in_flow: return

        if aka.startswith('#'):
            self.backup_man.set_dirty()
            man.in_flow = False
            return

        try:
            ret, ex = await self.draw(aka)
            if ex:
                self.backup_man.set_dirty()
                man.in_flow = False
            return ret
        except Exception as e:
            self.backup_man.set_dirty()
            man.in_flow = False
            return [
                f' 退出了连续抽奖模式, 原因: ',
                *e.args
            ]
        
    @any_instr()
    async def in_flow_draw_img_exit(self, _: Image, man: UserVoucherMan):
        if not man.in_flow: return

        self.backup_man.set_dirty()
        man.in_flow = False

    @top_instr('兑奖券')
    async def get_ticket_cnt(self, man: Optional[UserVoucherMan]):
        cnt = 0
        if man is not None:
            cnt = man.count
        
        return [f'你当前共持有{cnt}张兑奖券']
    
    @top_instr('赠送')
    async def give_ticket(self, at: Optional[At], me: GroupMember):
        info: MemberInfoModel = await self.bot.member_info(me.group.id, me.id).get()
        if info is None:
            return ['无法获取成员信息']
        
        if info.active.temperature < 50:
            return ['赠送失败: 等级过低']

        if at is None:
            return ['请指定赠予对象']
        
        consume_id = await self.consume(cnt=Decimal('1.1'))
        member = await self.member_from(at=at)
        async with self.override(member):
            await self.recv_ticket(consume_id=consume_id, count=Decimal('1'))
        return [' 向', at, ' 赠送了一张兑奖券']

    @delegate(InstrAttr.FORECE_BACKUP)
    async def recv_ticket(self, man: UserVoucherMan, *, consume_id: float, count: Decimal):
        man.append_gift(GiftRecord(consume_id=consume_id, count=count))

    @top_instr('抽奖', InstrAttr.FORECE_BACKUP)
    async def draw_cmd(self, aka: Optional[str], man: UserVoucherMan):

        if aka is None:
            obtained_achvs: list[AchvInfo] = [typing.cast(AchvInfo, a.value) for a in await self.achv.get_obtained()]
            filtered_achvs = [a for a in obtained_achvs if a.opts.rarity in self.PROBS.keys()]

            def comp(it: AchvInfo):
                return typing.cast(AchvRarityVal, it.opts.rarity.value).level

            sorted_achvs: list[AchvInfo] = sorted(filtered_achvs, key=comp)
            grouped = groupby(sorted_achvs, lambda it: it.opts.rarity)

            avaliable_achvs = [f'[{typing.cast(AchvRarityVal, k.value).aka} {self.PROBS[k] * 100:.0f}%] {", ".join([a.aka for a in g])}' for k, g in grouped]
            if len(avaliable_achvs) == 0:
                avaliable_achvs = ['暂时还没有, 请继续保持努力哦']
            else:
                man.in_flow = True

            example_achv_aka = next((a.aka for a in filtered_achvs), '连五鞭')

            return '\n'.join([
                '消耗一个成就抽取兑奖券🐱🐾', 
                f'抽奖方式: 请直接发送<成就名>进行连续抽奖, 如发送 {example_achv_aka}',
                '', 
                # '获奖概率：', 
                # *prob_texts, 
                # f'*惩罚倍率: {self.MAG_PUNISHMENT * 100:.0f}%',
                # '',
                '可用于抽奖的成就: ',
                *avaliable_achvs
            ])
        
        man.in_flow = False
        ret, ex = await self.draw(aka)
        return ret

 