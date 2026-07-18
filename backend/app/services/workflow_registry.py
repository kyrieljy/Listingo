from __future__ import annotations

import json
from typing import Any


REQUIRED_NODE_TYPES = ["input", "product_vision", "meta_prompt", "llm", "contract", "semantic_validator", "image_generate", "aggregate"]
ALLOWED_EDGES = {
    ("input", "product_vision"),
    ("product_vision", "meta_prompt"),
    ("meta_prompt", "llm"),
    ("llm", "contract"),
    ("contract", "semantic_validator"),
    ("semantic_validator", "image_generate"),
    ("image_generate", "aggregate"),
}


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


def validate_workflow_graph(graph: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    by_id = {node.get("id"): node for node in nodes if node.get("id")}
    types = [node.get("type") for node in nodes]
    for node_type in REQUIRED_NODE_TYPES:
        if types.count(node_type) != 1:
            errors.append(f"节点 {node_type} 必须且只能存在一个")
    for edge in edges:
        source = by_id.get(edge.get("source"))
        target = by_id.get(edge.get("target"))
        if not source or not target:
            errors.append(f"连线 {edge.get('id', 'unknown')} 引用了不存在的节点")
            continue
        if (source.get("type"), target.get("type")) not in ALLOWED_EDGES:
            errors.append(f"不允许的连线：{source.get('type')} → {target.get('type')}")
    if len(edges) != 7:
        errors.append("一期 Workflow 必须包含 7 条标准连线")
    return errors


def default_workflow_json() -> str:
    return json.dumps(DEFAULT_WORKFLOW_GRAPH, ensure_ascii=False, separators=(",", ":"))
