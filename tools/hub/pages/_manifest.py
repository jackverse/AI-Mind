# -*- coding: utf-8 -*-
"""自动生成，别手改：python tools/hub/discover.py --write

打包成 exe 后 pages/*.py 源码不在磁盘上，hub 靠这份清单还原侧栏与每日任务。
"""

PAGES = {
    'home': ('◎', '首页', '总览', 'pages.home', 100),
    'notes': ('☰', '笔记', '全部 md', 'pages.notes', 90),
    'quiz': ('✎', '刷题', '随机/章节', 'pages.quiz', 80),
    'fitness': ('♥', '健身', '体重/打卡', 'pages.fitness', 70),
    'timeline': ('≡', '时间线', '在干嘛', 'pages.timeline', 68),
    'house': ('⌂', '买房', '首付/月供/房源', 'pages.house', 67),
    'douyin': ('♪', '抖音', '账号数据', 'pages.douyin', 65),
    'eudic': ('英', '欧路', '生词/学习', 'pages.eudic', 63),
    'xhs': ('✿', '小红书', '笔记数据', 'pages.xhs', 60),
    'bills': ('¥', '账单', '支付宝/微信', 'pages.bills', 58),
    'inbox': ('⤓', '收集箱', '丢文件进来', 'pages.inbox', 57),
    'mail': ('✉', '邮件', '提醒/日报', 'pages.mail', 56),
    'wrong': ('✗', '错题本', '待攻克', 'pages.wrong', 40),
    'stats': ('▦', '统计', '正确率', 'pages.stats', 30),
    'settings': ('⚙', '设置', '排序/模块', 'pages.settings', 20),
}

DAILY = [
    {'key': 'douyin_sync', 'label': '抖音', 'module': 'core.douyin_sync', 'func': 'main_cli', 'weight': 90},
    {'key': 'xhs_sync', 'label': '小红书', 'module': 'core.xhs_sync', 'func': 'main_cli', 'weight': 80},
    {'key': 'bill_sync', 'label': '支付宝账单', 'module': 'core.bill_sync', 'func': 'daily_cli', 'weight': 70},
    {'key': 'eudic', 'label': '欧路词典', 'module': 'core.eudic', 'func': 'daily_cli', 'weight': 60},
    {'key': 'collect', 'label': '收集箱', 'module': 'core.collect', 'func': 'daily_cli', 'weight': 50},
]
