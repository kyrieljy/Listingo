from __future__ import annotations

import copy
import json
from typing import Any


DEFAULT_WORKFLOW_GRAPH: dict[str, Any] = {
    "schema_version": "1.0",
    "viewport": {"x": 30, "y": 90, "zoom": 0.9},
    "nodes": [
        {"id": "input", "type": "input", "position": {"x": 40, "y": 180}, "data": {"label": "输入校验"}},
        {"id": "vision", "type": "product_vision", "position": {"x": 250, "y": 180}, "data": {"label": "商品视觉事实"}},
        {"id": "meta", "type": "meta_prompt", "position": {"x": 460, "y": 180}, "data": {"label": "Meta Prompt"}},
        {"id": "llm", "type": "llm", "position": {"x": 670, "y": 180}, "data": {"label": "LLM JSON"}},
        {"id": "contract", "type": "contract", "position": {"x": 880, "y": 180}, "data": {"label": "结构校验"}},
        {"id": "semantic", "type": "semantic_validator", "position": {"x": 1090, "y": 180}, "data": {"label": "语义审查"}},
        {"id": "image", "type": "image_generate", "position": {"x": 1300, "y": 180}, "data": {"label": "并发生图"}},
        {"id": "aggregate", "type": "aggregate", "position": {"x": 1510, "y": 180}, "data": {"label": "结果聚合"}},
    ],
    "edges": [
        {"id": "e-input-vision", "source": "input", "target": "vision"},
        {"id": "e-vision-meta", "source": "vision", "target": "meta"},
        {"id": "e-meta-llm", "source": "meta", "target": "llm"},
        {"id": "e-llm-contract", "source": "llm", "target": "contract"},
        {"id": "e-contract-semantic", "source": "contract", "target": "semantic"},
        {"id": "e-semantic-image", "source": "semantic", "target": "image"},
        {"id": "e-image-aggregate", "source": "image", "target": "aggregate"},
    ],
}

VIDEO_WORKFLOW_GRAPH: dict[str, Any] = {
    "schema_version": "1.0",
    "viewport": {"x": 30, "y": 90, "zoom": 0.9},
    "nodes": [
        {"id": "input", "type": "input", "position": {"x": 40, "y": 180}, "data": {"label": "输入校验"}},
        {"id": "vision", "type": "product_vision", "position": {"x": 250, "y": 180}, "data": {"label": "商品视觉事实"}},
        {"id": "video_meta", "type": "video_meta_prompt", "position": {"x": 460, "y": 180}, "data": {"label": "视频 Meta Prompt"}},
        {"id": "script", "type": "llm", "position": {"x": 670, "y": 180}, "data": {"label": "导演脚本 JSON"}},
        {"id": "contract", "type": "contract", "position": {"x": 880, "y": 180}, "data": {"label": "脚本结构校验"}},
        {"id": "video", "type": "video_generate", "position": {"x": 1090, "y": 180}, "data": {"label": "视频提交与轮询"}},
        {"id": "aggregate", "type": "aggregate", "position": {"x": 1300, "y": 180}, "data": {"label": "结果聚合"}},
    ],
    "edges": [
        {"id": "e-input-vision", "source": "input", "target": "vision"},
        {"id": "e-vision-video-meta", "source": "vision", "target": "video_meta"},
        {"id": "e-video-meta-script", "source": "video_meta", "target": "script"},
        {"id": "e-script-contract", "source": "script", "target": "contract"},
        {"id": "e-contract-video", "source": "contract", "target": "video"},
        {"id": "e-video-aggregate", "source": "video", "target": "aggregate"},
    ],
}

APLUS_WORKFLOW_GRAPH: dict[str, Any] = {
    "schema_version": "1.0",
    "viewport": {"x": 30, "y": 90, "zoom": 0.9},
    "nodes": [
        {"id": "input", "type": "input", "position": {"x": 40, "y": 180}, "data": {"label": "输入校验"}},
        {"id": "vision", "type": "product_vision", "position": {"x": 250, "y": 180}, "data": {"label": "商品视觉事实"}},
        {"id": "aplus_meta", "type": "aplus_meta_prompt", "position": {"x": 460, "y": 180}, "data": {"label": "A+ Meta Prompt"}},
        {"id": "llm", "type": "llm", "position": {"x": 670, "y": 180}, "data": {"label": "模块 JSON"}},
        {"id": "router", "type": "module_router", "position": {"x": 880, "y": 180}, "data": {"label": "模块路由"}},
        {"id": "web_image", "type": "image_generate", "position": {"x": 1090, "y": 132}, "data": {"label": "详情 / A+ 生图"}},
        {"id": "mobile_edit", "type": "image_edit", "position": {"x": 1090, "y": 230}, "data": {"label": "高级移动端生成/派生"}},
        {"id": "aggregate", "type": "aggregate", "position": {"x": 1320, "y": 180}, "data": {"label": "结果聚合"}},
    ],
    "edges": [
        {"id": "e-input-vision", "source": "input", "target": "vision"},
        {"id": "e-vision-aplus-meta", "source": "vision", "target": "aplus_meta"},
        {"id": "e-aplus-meta-llm", "source": "aplus_meta", "target": "llm"},
        {"id": "e-llm-router", "source": "llm", "target": "router"},
        {"id": "e-router-web-image", "source": "router", "target": "web_image"},
        {"id": "e-router-mobile-edit", "source": "router", "target": "mobile_edit"},
        {"id": "e-web-image-mobile-edit", "source": "web_image", "target": "mobile_edit"},
        {"id": "e-web-image-aggregate", "source": "web_image", "target": "aggregate"},
        {"id": "e-mobile-edit-aggregate", "source": "mobile_edit", "target": "aggregate"},
    ],
}

WORKFLOW_PRESETS: tuple[dict[str, Any], ...] = (
    {
        "code": "product-suite-v1",
        "name": "商品套图生成",
        "description": "输入校验 → 商品视觉事实 → Meta Prompt → 结构/语义校验 → 并发生图 → 聚合",
        "graph": DEFAULT_WORKFLOW_GRAPH,
        "change_note": "一期标准 Workflow 注册",
    },
    {
        "code": "video-v1",
        "name": "视频生成与复刻",
        "description": "输入校验 → 商品视觉事实 → 视频 Meta Prompt → 导演脚本 → 视频生成 → 聚合",
        "graph": VIDEO_WORKFLOW_GRAPH,
        "change_note": "视频 Workflow 注册",
    },
    {
        "code": "aplus-detail-v1",
        "name": "A+详情页生成",
        "description": "输入校验 → 商品视觉事实 → A+ Meta Prompt → 模块路由 → 生图 / 移动端生成或派生 → 聚合",
        "graph": APLUS_WORKFLOW_GRAPH,
        "change_note": "二期详情页 Workflow 注册",
    },
)


def validate_workflow_graph(graph: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if graph.get("schema_version") != "1.0":
        errors.append("Workflow schema_version 必须为 1.0")
    if not isinstance(nodes, list) or not nodes:
        errors.append("Workflow 必须包含节点")
        return errors
    if not isinstance(edges, list):
        errors.append("Workflow edges 必须是数组")
        return errors
    by_id = {node.get("id"): node for node in nodes if node.get("id")}
    types = [node.get("type") for node in nodes]
    if len(by_id) != len(nodes):
        errors.append("节点 id 必须存在且不能重复")
    for node in nodes:
        if not node.get("type"):
            errors.append(f"节点 {node.get('id', 'unknown')} 缺少 type")
    for node_type in ("input", "aggregate"):
        if types.count(node_type) != 1:
            errors.append(f"节点 {node_type} 必须且只能存在一个")
    incoming: dict[str, int] = {node_id: 0 for node_id in by_id}
    outgoing: dict[str, int] = {node_id: 0 for node_id in by_id}
    edge_pairs: set[tuple[str, str]] = set()
    for edge in edges:
        source_id = edge.get("source")
        target_id = edge.get("target")
        source = by_id.get(source_id)
        target = by_id.get(target_id)
        if not source or not target:
            errors.append(f"连线 {edge.get('id', 'unknown')} 引用了不存在的节点")
            continue
        pair = (str(source_id), str(target_id))
        if pair in edge_pairs:
            errors.append(f"重复连线：{source_id} → {target_id}")
        edge_pairs.add(pair)
        outgoing[str(source_id)] += 1
        incoming[str(target_id)] += 1
    for node in nodes:
        node_id = str(node.get("id"))
        node_type = node.get("type")
        if node_type != "input" and incoming.get(node_id, 0) == 0:
            errors.append(f"节点 {node_type} 缺少上游连线")
        if node_type != "aggregate" and outgoing.get(node_id, 0) == 0:
            errors.append(f"节点 {node_type} 缺少下游连线")
    return errors


def default_workflow_json() -> str:
    return json.dumps(DEFAULT_WORKFLOW_GRAPH, ensure_ascii=False, separators=(",", ":"))


def workflow_preset_dicts() -> list[dict[str, Any]]:
    return [
        {
            **preset,
            "graph": copy.deepcopy(preset["graph"]),
        }
        for preset in WORKFLOW_PRESETS
    ]
