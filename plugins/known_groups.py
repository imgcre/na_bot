from typing import Iterator, Set
from plugin import Plugin, instr, route, enable_backup

@route('群')
@enable_backup
class KnownGroups(Plugin):
    _group_ids: Set[int] = {139825481}

    def __iter__(self) -> Iterator[int]:
        return self._group_ids.__iter__()

    @instr('list')
    async def list(self):
        sl = []
        for g_id in self._group_ids:
            group = await self.bot.get_group(g_id)
            sl.append(f'{group.name} ({group.id})')
        return [
            'bot可访问的群:\n',
            '\n'.join(sl)
        ]
    
    # @instr('add')
    # @admin
    # async def add(self, id: int):
    #     if id in self._group_ids:
    #         return [f'目标群{id}已存在']
    #     self._group_ids.add(id)
    #     self.backup_man.set_dirty()
    #     return ['添加成功']
    
    # @instr('remove')
    # @admin
    # async def remove(self, id: int):
    #     if id not in self._group_ids:
    #         return [f'目标群{id}不在已知群中']
    #     self._group_ids.remove(id)
    #     self.backup_man.set_dirty()
    #     return ['删除成功']
    



