"""首页灵感主题 API。

当前使用本地演示数据，便于在不依赖外部热榜和爬虫的情况下验证完整交互。
未来可在此替换为已授权的数据源，并保持响应契约不变。
"""

from datetime import date

from flask import Blueprint, jsonify


LOCAL_DEMO_TRENDS = [
    {
        "rank": 1,
        "title": "夏日通勤穿搭：清爽显瘦的 5 套搭配",
        "category": "穿搭",
        "topic": "写一篇夏日通勤穿搭教程：面向上班族，给出 5 套清爽显瘦搭配、适用场景和避雷建议。",
    },
    {
        "rank": 2,
        "title": "10 分钟高蛋白早餐备餐",
        "category": "美食",
        "topic": "写一篇 10 分钟高蛋白早餐备餐教程：包含食材清单、制作步骤、热量与蛋白质估算。",
    },
    {
        "rank": 3,
        "title": "周末城市公园散步路线",
        "category": "旅行",
        "topic": "写一篇周末城市公园散步攻略：包含路线规划、拍照点、穿搭建议和半日时间安排。",
    },
    {
        "rank": 4,
        "title": "桌面整理：提升专注力的小改造",
        "category": "效率",
        "topic": "写一篇桌面整理教程：用低预算完成办公桌收纳、线材整理和专注环境布置。",
    },
    {
        "rank": 5,
        "title": "新手护肤：建立基础护肤流程",
        "category": "护肤",
        "topic": "写一篇新手基础护肤教程：按早晚流程说明清洁、保湿、防晒，并给出常见误区。",
    },
    {
        "rank": 6,
        "title": "用手机拍出自然氛围感照片",
        "category": "摄影",
        "topic": "写一篇手机人像拍照教程：讲解光线、构图、姿势和后期调整，适合零基础用户。",
    },
]


def create_trend_blueprint():
    trend_bp = Blueprint("trend", __name__)

    @trend_bp.route("/trends", methods=["GET"])
    def get_trends():
        return jsonify({
            "success": True,
            "source": "local_demo",
            "updated_at": date.today().isoformat(),
            "trends": LOCAL_DEMO_TRENDS,
        })

    return trend_bp
