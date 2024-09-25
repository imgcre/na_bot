import time

from mirai import GroupMessage, Image, Plain

import mirai.models.message
from mirai.models.entities import GroupMember
from plugin import Plugin, top_instr, any_instr, InstrAttr, route, PathArg
import random
import random
from PIL import Image as img
from PIL.Image import Image as PImage
import aiohttp
import aiofile
from enum import Enum, auto

from utilities import get_logger

logger = get_logger()

class Dir(Enum):
    小威 = auto()

@route('梗')
class Stem(Plugin):
    last_run_time: int

    def __init__(self) -> None:
        self.last_run_time = time.time()

    @top_instr('(?P<which>原神|vscode).*?启动.*?', InstrAttr.NO_ALERT_CALLER)
    async def impa(self, which: PathArg[str]):
        pic_name = 'impa.jpg' if which == '原神' else 'vscode.jpg'
        return [
            mirai.models.message.Image(path=self.path.data.of_file(pic_name))
        ]
    
    @top_instr('关机|关闭', InstrAttr.NO_ALERT_CALLER)
    async def shutdown(self):
        return [
            mirai.models.message.Image(path=self.path.data.of_file('关机.jpg'))
        ]
    
    @any_instr(InstrAttr.NO_ALERT_CALLER)
    async def auto_impa(self, event: GroupMessage):
        for c in event.message_chain:
            if isinstance(c, Plain):
                if '行' in c.text and random.random() < 0.2:
                    return [
                        mirai.models.message.Image(path=self.path.data.of_file('行.jpg'))
                    ]

    # @any_instr(InstrAttr.NO_ALERT_CALLER)
    # async def auto_impa(self, event: GroupMessage):
    #     now = time.time()
    #     if event.sender.id == 928079017 and (now - self.last_run_time > 60 * 60):
    #         self.last_run_time = now
    #         return await self.impa()

    @top_instr('打卡', InstrAttr.NO_ALERT_CALLER)
    async def check_in(self, member: GroupMember):
        avatar_url = member.get_avatar_url()
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url) as resp:
                assert resp.status == 200
                data = await resp.read()
        file_name = f'{member.id}.jpg'
        file_path = self.path.data.cache.of_file(file_name)
        async with aiofile.async_open(file_path, "wb") as outfile:
            await outfile.write(data)
        
        im_front: PImage = img.open(self.path.data.of_file('check_in_front.png'))
        im_target: PImage = img.new('RGBA', im_front.size, (0, 0, 0, 0))
        im_avatar: PImage = img.open(file_path)

        im_avatar.thumbnail((139, 139), img.Resampling.LANCZOS)
        im_target.paste(im_avatar, (317, 429 - 22))
        im_target.paste(im_front, (0, 0), im_front)

        target_file_name = f'{member.id}.png'
        target_file_path = self.path.data.cache.of_file(target_file_name)
        im_target.save(target_file_path, "PNG")

        return [
            mirai.models.message.Image(path=target_file_path)
        ]
    
    @top_instr("吃什么")
    async def eat_what(self):
        foods = [
            "红烧肉",
            "红烧排骨",
            "可乐鸡翅",
            "糖醋排骨",
            "水煮鱼",
            "红烧鱼",
            "凉拌黑木耳",
            "鱼香肉丝",
            "水煮肉片",
            "意大利面",
            "麻辣小龙虾",
            "凉拌木耳",
            "茶叶蛋",
            "龙井虾仁",
            "口水鸡",
            "回锅肉",
            "红烧猪蹄",
            "皮蛋瘦肉粥",
            "酸菜鱼",
            "咖喱牛肉",
            "西红柿炒鸡蛋",
            "辣椒酱",
            "麻辣烫",
            "辣白菜",
            "牛肉酱",
            "红烧茄子",
            "蛋炒饭",
            "佛跳墙",
            "四物汤",
            "固元膏",
            "龟苓膏",
            "银耳莲子羹",
            "酸梅汤",
            "腊肉",
            "酸辣土豆丝",
            "煎蛋",
            "鱼香茄子",
            "啤酒鸭",
            "麻婆豆腐",
            "宫保鸡丁",
            "手撕包菜",
            "剁椒鱼头",
            "粉蒸肉",
            "锅包肉",
            "麻辣香锅",
            "红烧牛肉",
            "辣子鸡",
            "牛肉炖土豆",
            "糖醋鲤鱼",
            "干煸豆角",
            "烧茄子",
            "炖排骨",
            "木须肉",
            "香辣虾",
            "红烧狮子头",
            "小鸡炖蘑菇",
            "糖醋里脊",
            "土豆炖牛肉",
            "板栗烧鸡",
            "糖醋鱼",
            "肉丸",
            "梅菜扣肉",
            "京酱肉丝",
            "红烧带鱼",
            "大盘鸡",
            "红烧鸡翅",
            "醋溜白菜",
            "香辣蟹",
            "地三鲜",
            "东坡肉",
            "葡萄酒",
            "鲫鱼豆腐汤",
            "鲫鱼汤",
            "鸡汤",
            "乌鸡汤",
            "鸽子汤",
            "冰糖炖雪梨",
            "银耳汤",
            "鱼头豆腐汤",
            "银耳莲子汤",
            "鸡蛋羹",
            "牛肉汤",
            "山药排骨汤",
            "冬瓜汤",
            "莲藕排骨汤",
            "羊肉汤",
            "猪肝汤",
            "罗宋汤",
            "酸辣汤",
            "臭豆腐",
            "清蒸大闸蟹",
            "醋溜土豆丝",
            "四川泡菜",
            "拔丝地瓜",
            "清蒸鲈鱼",
            "孜然羊肉",
            "银耳红枣汤",
            "麻辣豆腐",
            "西红柿炖牛腩",
            "炖鸡",
            "排骨汤",
            "关东煮",
            "烤鱼",
            "香菇油菜",
            "毛血旺",
            "泡椒凤爪",
            "酱牛肉",
            "辣子鸡丁",
            "咖喱鸡",
            "椒盐虾",
            "寿司",
            "家常豆腐",
            "司康",
            "花卷",
            "熘肝尖",
            "戚风蛋糕",
            "牛肉面",
            "包子",
            "燕麦饼干",
            "饺子",
            "玛格丽特饼干",
            "曲奇饼干",
            "烧卖",
            "慕斯蛋糕",
            "沙拉",
            "手指饼干",
            "珍珠丸子",
            "吐司",
            "芝士蛋糕",
            "窝窝头",
            "发糕",
            "自制凉皮",
            "肉松面包",
            "千层肉饼",
            "红焖羊肉",
            "葱爆羊肉",
            "油焖大虾",
            "骨头汤",
            "拔丝山药",
            "蒜蓉西兰花",
            "葱油饼",
            "南瓜饼",
            "炸酱面",
            "卤肉饭",
            "咖喱饭",
            "豆腐脑",
            "南瓜粥",
            "汉堡",
            "饭团",
            "鸡蛋饼",
            "方便面",
            "馒头",
            "土豆泥",
            "甜甜圈",
            "酸辣粉",
            "炒年糕",
            "双皮奶",
            "炒面",
            "鸡蛋糕",
            "糖炒栗子",
            "油条",
            "豆沙包",
            "奶黄包",
            "披萨",
            "八宝粥",
            "蛋挞",
            "乳酪蛋糕",
            "全麦面包",
            "芝士面包",
            "糯米藕",
            "生日蛋糕",
            "毛毛虫面包",
            "菠菜鸡蛋汤",
            "泡芙",
            "冰激凌",
            "酸奶蛋糕",
            "电饭锅蛋糕",
            "布朗尼",
            "派",
            "马芬",
            "巧克力蛋糕",
            "菊花酥",
            "酥饼",
            "椰蓉球",
            "黑森林蛋糕",
            "豆沙面包",
            "提拉米苏",
            "海绵蛋糕",
            "冰皮月饼",
            "酥皮月饼",
            "五仁月饼",
            "苏式月饼",
            "疙瘩汤",
            "糖不甩",
            "秋梨膏",
            "三杯鸡",
            "锅贴",
            "苦瓜炒肉片",
            "拍黄瓜",
            "宫保虾球",
            "尖椒土豆片",
            "炸茄盒",
            "苦瓜酿肉",
            "荷叶饼",
            "芹菜炒香干",
            "炸耦合",
            "焦糖布丁",
            "白菜炖豆腐",
            "蚂蚁上树",
            "盐水鸭",
            "韭菜炒香干",
            "肉夹馍",
            "奶茶",
            "爆米花",
            "紫菜包饭",
            "苹果醋",
            "豆角焖面",
            "打卤面",
            "香卤鹌鹑蛋",
            "老醋花生",
            "麻辣鸭脖",
            "盐水花生",
            "油泼鱼",
            "西湖牛肉羹",
            "麻团",
            "宫保豆腐",
            "菠菜塔",
            "自制剁椒",
            "手撕杏鲍菇",
            "蓑衣黄瓜",
            "剁椒鸡丁",
            "麻酱豆角",
            "上校鸡块",
            "红烧鸡爪",
            "自制酸奶",
            "松仁玉米",
            "红烧冬瓜",
            "牛肉干",
            "冬瓜排骨汤",
            "凉面",
            "猪肉脯",
            "珍珠圆子",
            "肉末酸豆角",
            "蛤蜊蒸蛋",
            "玉米饼",
            "菠菜炒鸡蛋",
            "西芹百合",
            "白灼芥蓝",
            "炒西瓜皮",
            "叫花鸡",
            "盐焗鸡",
            "冰糖湘莲",
            "鸭血粉丝汤",
            "青椒土豆丝",
            "棒棒鸡",
            "锅塌豆腐",
            "水晶虾饺",
            "拔丝苹果",
            "茄汁带鱼",
            "荷叶粉蒸肉",
            "石锅拌饭",
            "爆炒腰花",
            "辣椒油",
            "韭菜盒子",
            "香辣酥",
            "蒜薹炒肉",
            "蒜蓉油麦菜",
            "腐乳烧鸡翅",
            "奶香馒头",
            "炒饼",
            "蛋包饭",
            "牛奶炖蛋",
            "鸡蛋灌饼",
            "荷塘小炒",
            "木耳炒肉",
            "脆皮炸鲜奶",
            "铜锣烧",
            "扬州炒饭",
            "照烧鸡",
            "自制豆腐",
            "芙蓉虾",
            "琥珀核桃",
            "酱油炒饭",
            "葱花饼",
            "虎皮青椒",
            "可乐饼",
            "奥尔良烤翅",
            "咸蛋黄焗南瓜",
            "上汤娃娃菜",
            "肉饼蒸蛋",
            "赛肘花",
            "蒜泥茄子",
            "虎皮凤爪",
            "芒果布丁",
            "香辣烤鱼",
            "把子肉",
            "奶昔",
            "铁板鱿鱼",
            "芝心虾球",
            "白灼虾",
            "木瓜椰奶冻",
            "农家小炒肉",
            "薯片",
            "烤羊肉串",
            "手抓饼",
            "阳春面",
            "松鼠鱼",
            "叉烧肉",
            "肉皮冻",
            "朝鲜冷面",
            "味增汤",
            "麻辣千张",
            "香椿鱼儿",
            "咖喱牛腩",
            "白灼菜心",
            "沙琪玛",
            "麻辣肉片",
            "糟溜鱼片",
            "面茶",
            "自来红",
            "韭菜炒鱿鱼",
            "大列巴",
            "艾窝窝",
            "馄饨",
            "糖三角",
            "糖渍金桔",
            "腊八粥",
            "五香毛豆",
            "炸香椿鱼",
            "杏仁豆腐",
            "肉龙",
            "凉拌海带丝",
            "春卷",
            "九转大肠",
            "东北乱炖",
            "黄桥烧饼",
            "葱烧海参",
            "清蒸武昌鱼",
            "蒜泥白肉",
            "腊味合蒸",
            "四喜丸子",
            "赛螃蟹",
            "盐水虾",
            "煎饼",
            "青椒炒鸡蛋",
            "萝卜汤",
            "肉片炒青椒",
            "黄瓜炒鸡蛋",
            "酸辣白菜",
            "红烧豆腐",
            "紫菜蛋花汤",
            "馒头片",
            "苦瓜炒鸡蛋",
            "皮蛋豆腐",
            "卤牛肉",
            "酱爆鸡丁",
            "青椒炒肉丝",
            "炒莴笋",
            "粉蒸排骨",
            "百财登门",
            "锅煲菜",
            "花样泡芙",
            "春天的沙拉",
            "早餐蛋饼"
        ]
        return [random.choice(foods)]
        ...

    @any_instr()
    async def coll_小威(self, event: GroupMessage):
        who = event.sender
        if who.id != 13975418:
            return
        for c in event.message_chain:
            if isinstance(c, Image):
                p = await c.download(directory=self.path.data[Dir.小威])
        