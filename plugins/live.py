import asyncio
from dataclasses import dataclass, field
import random
import string
import time
import traceback
import typing
import config
from plugin import Context, Inject, Plugin, any_instr, autorun, delegate, enable_backup, InstrAttr, route, top_instr
from aiomqtt import Client
import aiomqtt
from mirai import At, AtAll, Image
from mirai.models.entities import GroupMember, Group, GroupConfigModel
from bilibili_api import live
import json

from typing import TYPE_CHECKING, Final

from utilities import AchvEnum, AchvInfo, AchvOpts, AchvRarity, GroupLocalStorage, UserSpec, breakdown_chain_sync, get_logger, throttle_config

if TYPE_CHECKING:
    from plugins.achv import Achv
    from plugins.bili import Bili
    from plugins.known_groups import KnownGroups
    from plugins.throttle import Throttle

logger = get_logger()

class LiveAchv(AchvEnum):
    CAPTAIN = 0, '舰长', '通过【#绑定账号】与B站账号相关联后并且是B站账号为纳延的舰长时自动获取', AchvOpts(rarity=AchvRarity.RARE, custom_obtain_msg='成为了猫咪的舰长', display='⚓', locked=True)
    ...

class BindState(): ...

@dataclass
class BindStateNotBind(BindState): ...

@dataclass
class BindStateWaitOpenId(BindState):
    from_group_id: int
    confirm_code: str = field(init=False)

    def __post_init__(self):
        self.confirm_code = ''.join(random.choices(string.ascii_lowercase, k=6))

@dataclass
class BindStateBound(BindState):
    openid: str = None
    uname: str = None

@dataclass
class UserBindInfo():
    bind_state: BindState = BindStateNotBind()
    def start_bind(self, from_group_id: int) -> str:
        self.bind_state = BindStateWaitOpenId(from_group_id=from_group_id)
        return self.bind_state.confirm_code
    
    def check_confirm_code(self, confirm_code: str):
        return isinstance(self.bind_state, BindStateWaitOpenId) and self.bind_state.confirm_code == confirm_code

    def end_bind(self, openid: str, uname: str):
        if not isinstance(self.bind_state, BindStateWaitOpenId):
            raise RuntimeError('state error')
        prev_state = self.bind_state
        self.bind_state = BindStateBound(openid=openid, uname=uname)
        return prev_state

    def is_bound(self):
        return isinstance(self.bind_state, BindStateBound)
    
    def get_openid(self):
        if not isinstance(self.bind_state, BindStateBound): return
        return self.bind_state.openid
    
    def check_open_id(self, openid: str):
        if not isinstance(self.bind_state, BindStateBound): return False
        return self.bind_state.openid ==openid
    
    def get_uname(self):
        if not isinstance(self.bind_state, BindStateBound): return
        return self.bind_state.uname

@dataclass
class CaptainMan():
    last_welcom_ts: int = 0

    WELCOME_INTERVAL: Final[int] = 60 * 60 * 8

    def is_need_welcome(self):
        return time.time() - self.last_welcom_ts > self.WELCOME_INTERVAL
    
    def set_welcomed(self):
        self.last_welcom_ts = time.time()


@route('live')
@enable_backup
class Live(Plugin):
    user_binds: UserSpec[UserBindInfo] = UserSpec[UserBindInfo]()
    gls_captain: GroupLocalStorage[CaptainMan] = GroupLocalStorage[CaptainMan]()

    achv: Inject['Achv']
    known_groups: Inject['KnownGroups']
    throttle: Inject['Throttle']

    def __init__(self) -> None:
        self.mqtt_client = None
        # cmd_name, req_id
        self.rpc_queue: dict[str, dict[str, asyncio.Future]] = {}
        self.is_living = False
        self.cmd_running = False
        self.ts_last_effect_set = 0
        self.ts_last_screenshot = 0
        ...

    @any_instr(InstrAttr.NO_ALERT_CALLER)
    async def auto_welcome_captain(self, member: GroupMember):
        if not await self.achv.is_used(LiveAchv.CAPTAIN):
            return
        
        man = self.gls_captain.get_or_create_data(member.group.id, member.id)
        if man.is_need_welcome():
            self.backup_man.set_dirty()
            man.set_welcomed()
            return [Image(path=self.path.data.of_file('captain.gif'))]

    @delegate()
    async def handle_message(self, message: aiomqtt.Message):
        logger.debug(f'{message.topic=}')
        if message.topic.matches('/live/status/started'):
            self.is_living = True
            room = live.LiveRoom(config.BILIBILI_LIVEROOM_ID)
            room_info = (await room.get_room_info())['room_info']
            title = room_info['title']
            cover_img_url = room_info['cover']
            room_id = room_info['room_id']

            for group_id in self.known_groups:
                # await self.bot.send_group_message(group_id, [
                #     f'📢小猫咪偷偷开播啦!\n{title}\nhttps://live.bilibili.com/{room_id}\n',
                #     mirai.models.message.Image(url=cover_img_url),
                #     '\n'.join([
                #         '目前可以用的指令:',
                #         '#点歌',
                #         '#点歌队列',
                #     ])
                # ])
                group = await self.bot.get_group(group_id)
                async with self.override(group):
                    await self.update_group_name_based_on_live_status()
                await self.bot.send_group_message(group_id, ['啵啦啵啦！', AtAll()])
                await self.bot.anno_publish(
                    group_id,
                    '\n'.join([
                        f'📢小猫咪偷偷开播啦!',
                        title,
                        f'https://live.bilibili.com/{room_id}',
                        '目前可以用的指令:',
                        '#点歌',
                        '#点歌队列',
                    ]),
                    send_to_new_member=True,
                    pinned=True,
                    show_edit_card=False,
                    show_popup=True,
                    require_confirmation=True,
                    image_url=cover_img_url
                )
        if message.topic.matches('/live/status/stopped'):
            self.is_living = False
            logger.debug('结束了')
            for group_id in self.known_groups:
                group = await self.bot.get_group(group_id)
                async with self.override(group):
                    await self.update_group_name_based_on_live_status()
        if message.topic.matches('/live/resp/+'):
            j = json.loads(message.payload)
            req_id = j['id']
            cmd_name = message.topic.value.split('/')[-1]
            if cmd_name in self.rpc_queue:
                cmd_sepc_queue = self.rpc_queue[cmd_name]
                if req_id in cmd_sepc_queue:
                    cmd_sepc_queue[req_id].set_result(j)
                    ...
                ...
            ...
        if message.topic.matches('/live/event/bind'):
            j = json.loads(message.payload)
            # openid uname confirm_code
            confirm_code = j['confirm_code']
            openid = j['openid']
            uname = j['uname']
            found_item = next((item for item in self.user_binds.users.items() if item[1].check_confirm_code(confirm_code)), None)
            if found_item is not None:
                qq_id, user_bind_info = found_item
                from_group_id = user_bind_info.end_bind(openid, uname).from_group_id
                await self.bot.send_group_message(from_group_id, [
                    At(target=qq_id),
                    f' 已与账号"{uname}"完成绑定'
                ])
                self.backup_man.set_dirty()
        if message.topic.matches('/live/event/guard'):
            j = json.loads(message.payload)
            openid = j['openid']
            found_item = next((item for item in self.user_binds.users.items() if item[1].check_open_id(openid)), None)

            if found_item is not None:
                qq_id, user_bind_info = found_item
                for group_id in self.known_groups:
                    member = await self.bot.get_group_member(group_id, qq_id)
                    if member is None: continue
                    async with self.override(member):
                        await self.achv.submit(LiveAchv.CAPTAIN)


    async def screenshoot(self):
        resp = await self.rpc('screenshoot')
        return resp['url']
    
    async def screen_record(self):
        resp = await self.rpc('screen_record', timeout=20)
        return resp['url']
    
    async def get_playlist(self):
        resp = await self.rpc('playlist')
        return resp['queue']
    
    async def add_music(self, query: str, openid: str, uname: str, avatar: str):
        resp = await self.rpc('add_music', {
            'query': query,
            'openid': openid,
            'uname': uname,
            'avatar': avatar
        })
        if not resp['success']:
            raise RuntimeError(resp['reason'])
        return resp['music_name']

    async def set_effect(self, name: str):
        await self.rpc('set_effect', {
            'name': name
        })

    async def rpc(self, name, data: dict = None, timeout: int=10) -> dict:
        if self.cmd_running:
            raise RuntimeError('请等待上一条指令执行完成')
            ...
        self.cmd_running = True
        if data is None:
            data = {}
        while True:
            req_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
            
            if name not in self.rpc_queue:
                self.rpc_queue[name] = {}

            if req_id in self.rpc_queue[name]:
                continue

            data['id'] = req_id
            break

        future = asyncio.Future()
        self.rpc_queue[name][req_id] = future

        await self.mqtt_client.publish(f'/live/req/{name}', json.dumps(data))

        try:
            await asyncio.wait_for(future, timeout)
        except TimeoutError:
            raise RuntimeError('服务未响应')
        finally:
            self.rpc_queue[name].pop(req_id)
            self.cmd_running = False
        
        return future.result()

    @top_instr('绑定账号', InstrAttr.FORECE_BACKUP)
    @throttle_config(name='账号绑定', max_cooldown_duration=30*60)
    async def bind_account(self, info: UserBindInfo, member: GroupMember):
        async with self.throttle as passed:
            if not passed: return
            
            if info.is_bound(): return '已完成绑定, 无需重复操作'
            if not self.is_living and member.id not in config.SUPER_ADMINS: return '当前未开播'

            confirm_code = info.start_bind(from_group_id=member.group.id)
            await self.bot.send_temp_message(member.id, member.group.id, [
                f'请在直播间发送弹幕(不要忘记后面的六位英文字母也要包括在弹幕中):'
            ])
            await asyncio.sleep(0.5)
            await self.bot.send_temp_message(member.id, member.group.id, [
                f'确认绑定{confirm_code}'
            ])
            
            return f'已开始绑定流程, 请留意bot发送的私信'

    @top_instr('截屏')
    async def screenshot_cmd(self, member: GroupMember):
        if not self.is_living and member.id not in config.SUPER_ADMINS: return '当前未开播'
        if time.time() - self.ts_last_screenshot < 10 * 60:
            return f'截屏过于频繁, 请{10 - (time.time() - self.ts_last_screenshot) // 60:.0f}分钟后再试'
        try:
            return [
                Image(url=await self.screenshoot())
            ]
        except RuntimeError as e:
            return ''.join(['截屏失败: ', *e.args])
        
    @top_instr('录屏', InstrAttr.NO_ALERT_CALLER)
    async def screen_record_cmd(self, member: GroupMember):
        if not self.is_living and member.id not in config.SUPER_ADMINS: return '当前未开播'
        if time.time() - self.ts_last_screenshot < 10 * 60:
            return f'录屏过于频繁, 请{10 - (time.time() - self.ts_last_screenshot) // 60:.0f}分钟后再试'
        try:
            return [
                Image(url=await self.screen_record())
            ]
        except RuntimeError as e:
            return ''.join(['录屏失败: ', *e.args])
    
    @delegate()
    async def set_effect_cmd(self, member: GroupMember, *, effect_name: str):
        obtained_achvs = await self.achv.get_obtained()
        
        obtained_rare_achvs = [achv for achv in obtained_achvs if typing.cast(AchvInfo, achv.value).opts.rarity.value.level >= AchvRarity.RARE.value.level]
        if len(obtained_rare_achvs) < 3 and member.id not in config.SUPER_ADMINS:
            return '使用本功能需要达成至少三项稀有及以上级别的成就'
        if not self.is_living and member.id not in config.SUPER_ADMINS: return '当前未开播'
        if time.time() - self.ts_last_effect_set < 5 * 60:
            return f'特效设置过于频繁, 请{5 - (time.time() - self.ts_last_effect_set) // 60:.0f}分钟后再试'
        try:
            await self.set_effect(effect_name)
            self.ts_last_effect_set = time.time()
            return '特效设置成功'
        except RuntimeError as e:
            return ''.join(['特效设置失败: ', *e.args])
        ...

    # @top_instr('镜头特效')
    # async def bobi_effect_cmd(self):
    #     return await self.set_effect_cmd(effect_name='Bobi')
    
    # @top_instr('玻璃球特效')
    # async def ball_effect_cmd(self):
    #     return await self.set_effect_cmd(effect_name='Ball')

    @top_instr('脸红特效')
    async def blush_effect_cmd(self):
        return await self.set_effect_cmd(effect_name='Blush')
        
    @top_instr('点歌')
    async def add_music_cmd(self, query: str, member: GroupMember, info: UserBindInfo):
        if not self.is_living and member.id not in config.SUPER_ADMINS: return '当前未开播'
        if not info.is_bound(): return '请先【#绑定账号】'

        try:
            music_name = await self.add_music(
                query=query,
                openid=info.get_openid(),
                uname=info.get_uname(),
                avatar=member.get_avatar_url()
            )
            return f'点播了歌曲《{music_name}》'
        except RuntimeError as e:
            return ''.join(['点歌失败: ', *e.args])

        
    @top_instr('点歌队列')
    async def playlist_cmd(self, member: GroupMember, info: UserBindInfo):
        if not self.is_living and member.id not in config.SUPER_ADMINS: return '当前未开播'
        li = await self.get_playlist()
        lines = [f'{item["uname"]}: 《{item["music_name"]}》' for item in li]
        return '\n'.join(lines)

    @delegate()
    async def update_group_name_based_on_live_status(self, group: Group):
        conf: GroupConfigModel = await self.bot.group_config(group.id).get()
        name_comps = breakdown_chain_sync(conf.name, rf"【(.*?)】", lambda s, ctx: None)
        if self.is_living:
            name_comps = ['【配信中】', *name_comps]
        await self.bot.group_config(group.id).set(conf.modify(name=''.join(name_comps)))

    @autorun
    async def conn_to_live_mqtt(self):
        self.mqtt_client = Client(
            "uf90fbf8.ala.cn-hangzhou.emqxsl.cn", 
            port=8883, 
            tls_params=aiomqtt.TLSParameters(
                ca_certs=self.path.data.of_file('emqxsl-ca.crt'),
            ), 
            username='guest', 
            password='guest'
        )
        interval = 5  # Seconds
        while True:
            try:
                async with self.mqtt_client:
                    logger.info('Connected')
                    await self.mqtt_client.subscribe("/live/status/+")
                    await self.mqtt_client.subscribe("/live/resp/+")
                    await self.mqtt_client.subscribe("/live/event/+")
                    await self.mqtt_client.publish('/live/query/status')
                    async for message in self.mqtt_client.messages:
                        try:
                            await self.handle_message(message)
                        except: 
                            traceback.print_exc()
            except aiomqtt.MqttError:
                logger.warning(f"Connection lost; Reconnecting in {interval} seconds ...")
                await asyncio.sleep(interval)
            except:
                traceback.print_exc()
