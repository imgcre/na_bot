import asyncio
from datetime import datetime
import time
import traceback
from plugin import Context, Inject, Plugin, any_instr, autorun, enable_backup, route

from typing import TYPE_CHECKING, Final

from utilities import AchvEnum, AchvOpts, get_logger
if TYPE_CHECKING:
    from plugins.known_groups import KnownGroups
    from plugins.achv import Achv

logger = get_logger()

class AutoPurgeAchv(AchvEnum):
    INACTIVE_MARK = 0, '潜水标记', '获得此标记三天内仍没有发言, 则将被清出群聊', AchvOpts(locked=True, hidden=True)
    ...

@route('auto_purge')
@enable_backup
class AutoPurge(Plugin):
    known_groups: Inject['KnownGroups']
    achv: Inject['Achv']

    INACTIVE_NOTIFICATION_DAYS_THRESHOLD: Final = 7
    INACTIVE_REMOVE_DAYS_THRESHOLD: Final = 3
    
    # 连续7天没有发言的话丢到待清除名单中
    # 在待清除名单中连续3天，则踢出群

    @autorun
    async def purge_process(self, ctx: Context):
        while True:
            await asyncio.sleep(1)
            with ctx:
                for group_id in self.known_groups:
                    resp = await self.bot.member_list(group_id)
                    group = await self.bot.get_group(group_id)

                    for i, member in enumerate(resp.data):
                        async with self.override(member):
                            try:
                                if member.special_title != '':
                                    continue

                                latest_active_day = max(member.join_timestamp, member.last_speak_timestamp)

                                span = datetime.now().replace(tzinfo=None) - latest_active_day.replace(tzinfo=None)

                                if span.days <= self.INACTIVE_NOTIFICATION_DAYS_THRESHOLD:
                                    
                                    await self.achv.remove(AutoPurgeAchv.INACTIVE_MARK, force=True)
                                    continue

                                if await self.achv.has(AutoPurgeAchv.INACTIVE_MARK):
                                    # TODO: 超过三天, 移除群聊, 顺便删除INACTIVE_MARK
                                    obtained_ts = await self.achv.get_achv_obtained_ts(AutoPurgeAchv.INACTIVE_MARK)
                                    if time.time() - obtained_ts > 60 * 60 * 24 * self.INACTIVE_REMOVE_DAYS_THRESHOLD:
                                        await self.bot.kick(group_id, member.id, '自动清理潜水群员, 误踢请重新加回')
                                        await self.achv.remove(AutoPurgeAchv.INACTIVE_MARK, force=True)
                                else:
                                    await self.achv.submit(AutoPurgeAchv.INACTIVE_MARK, silent=True)
                                    await self.bot.send_temp_message(member.id, group_id, [
                                        f'您在群{group.get_name()}({group_id})已经有{span.days}天没有冒泡啦, '
                                        f'bot将在{self.INACTIVE_REMOVE_DAYS_THRESHOLD}天后执行自动清理潜水群员程序, '
                                        '在此期间内进行冒泡可避免被误踢, 如被误踢请重新加回'
                                    ])
                                    logger.debug(f'[潜水通知] ({i + 1}/{len(resp.data)}) {member.get_name()}: {span.days}天')
                                    await asyncio.sleep(60)
                            except:
                                traceback.print_exc()

            await asyncio.sleep(60 * 60)
    
    @any_instr()
    async def remove_inactive_mark(self):
        await self.achv.remove(AutoPurgeAchv.INACTIVE_MARK, force=True)