# -*- coding: utf-8 -*-
"""自动生成，别手改：python tools/hub/discover.py --write

打包成 exe 后 pages/*.py 源码不在磁盘上，hub 靠这份清单还原侧栏与每日任务。
"""

PAGES = {
    'home': ('◎', '首页', '总览', 'pages.home', 100),
    'douyin': ('♪', '抖音', '账号数据', 'pages.douyin', 65),
    'xhs': ('✿', '小红书', '笔记数据', 'pages.xhs', 60),
    'me': ('◉', '我的', '设置/反馈', 'pages.me', 20),
}

DAILY = [
    {'key': 'douyin_sync', 'label': '抖音', 'module': 'core.douyin_sync', 'func': 'main_cli', 'weight': 90},
    {'key': 'xhs_sync', 'label': '小红书', 'module': 'core.xhs_sync', 'func': 'main_cli', 'weight': 80},
    {'key': 'bill_sync', 'label': '支付宝账单', 'module': 'core.bill_sync', 'func': 'daily_cli', 'weight': 70},
    {'key': 'eudic', 'label': '欧路词典', 'module': 'core.eudic', 'func': 'daily_cli', 'weight': 60},
    {'key': 'collect', 'label': '收集箱', 'module': 'core.collect', 'func': 'daily_cli', 'weight': 50},
]
