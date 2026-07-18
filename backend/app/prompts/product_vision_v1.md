# Listingo 商品视觉事实提取

读取全部商品参考图，只记录图中可观察事实和用户明确提供的信息。禁止推测不可见的材质、容量、认证、功效、销量或配件。

仅输出 JSON：
{"schema_version":"1.0","product_name":"","category":"","visible_features":[],"materials":[],"colors":[],"sku_count":1,"accessories":[],"labels_text":[],"uncertain":[]}

无法从图片确认的内容写入 uncertain；不得为了填满字段而编造。
