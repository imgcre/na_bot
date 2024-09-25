from plugin import Plugin, instr, InstrAttr, route, PathArg

@route('man')
class Man(Plugin):
    # @instr('list', InstrAttr.NO_ALERT_CALLER)
    # @admin
    # async def list(self):
    #     ll = []
    #     for k in self.engine.plugins.keys():
    #         p = self.engine.plugins[k]
    #         enabled_str = '已启用' if not p.disabled else '已禁用'
    #         ll.append(f'{k} {enabled_str}')
    #     return '\n'.join(ll)

    # @instr('(?P<state>enable|disable)', InstrAttr.NO_ALERT_CALLER)
    # @admin
    # async def disable(self, plugin_name: str, state: PathArg[str]):
    #     print(f'next state -> {state}')
    #     def change_state(p: Plugin):
    #         if state == 'enable':
    #             p.enable()
    #         else:
    #             p.disable()

    #     if plugin_name == 'all':
    #         for p in self.engine.plugins.values():
    #             if p is not self:
    #                 change_state(p)
    #     else:
    #         if plugin_name not in self.engine.plugins:
    #             return '指定插件不存在'
    #         change_state(self.engine.plugins[plugin_name])
    #     return f'{plugin_name} -> {state}'
    ...