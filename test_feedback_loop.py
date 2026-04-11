"""Test: feedback-loop enrichment with agent mode."""

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from llm.gateway_client import GatewayTaskClient


async def main() -> None:
    client = GatewayTaskClient(
        gateway_ws_url="ws://localhost:9090/acp/v1/connect",
        gateway_http_url="http://localhost:9090",
        api_key="sk-admin-test",
        model="gemini-3-flash",
        timeout=120,
    )

    items = [
        {
            "file": "src/main/java/com/example/order/OrderController.java",
            "name": "OrderController",
            "signature": "public class OrderController",
            "docstring": "订单管理控制器",
            "code_snippet": "@RestController\n@RequestMapping(\"/api/orders\")\npublic class OrderController {\n    @Autowired private OrderService orderService;\n}",
        },
        {
            "file": "src/main/java/com/example/order/OrderController.java",
            "name": "createOrder",
            "signature": "public OrderResponse createOrder(@RequestBody CreateOrderRequest request)",
            "docstring": "创建新订单",
            "code_snippet": "@PostMapping\npublic OrderResponse createOrder(@RequestBody CreateOrderRequest request) {\n    Order order = orderService.createOrder(request.getUserId(), request.getItems(), request.getShippingAddress());\n    return OrderResponse.fromOrder(order);\n}",
        },
        {
            "file": "src/main/java/com/example/order/OrderController.java",
            "name": "cancelOrder",
            "signature": "public OrderResponse cancelOrder(@PathVariable Long orderId)",
            "docstring": "取消订单",
            "code_snippet": "@PostMapping(\"/{orderId}/cancel\")\npublic OrderResponse cancelOrder(@PathVariable Long orderId) {\n    return OrderResponse.fromOrder(orderService.cancelOrder(orderId));\n}",
        },
        {
            "file": "src/main/java/com/example/order/OrderController.java",
            "name": "getOrderDetail",
            "signature": "public OrderDetailResponse getOrderDetail(@PathVariable Long orderId)",
            "docstring": "获取订单详情",
            "code_snippet": "@GetMapping(\"/{orderId}\")\npublic OrderDetailResponse getOrderDetail(@PathVariable Long orderId) {\n    return OrderDetailResponse.fromDetail(orderService.getOrderDetail(orderId));\n}",
        },
        {
            "file": "src/main/java/com/example/order/OrderController.java",
            "name": "listOrders",
            "signature": "public PageResponse<OrderResponse> listOrders(...)",
            "docstring": "查询用户订单列表",
            "code_snippet": "@GetMapping\npublic PageResponse<OrderResponse> listOrders(@RequestParam Long userId, @RequestParam(required=false) String status, int page, int size) {\n    return orderService.listOrders(userId, status, page, size);\n}",
        },
    ]

    print(f"\n=== Testing feedback-loop enrichment: {len(items)} items in one task ===\n")
    results = await client.enrich_batch(items)

    for item, summary in zip(items, results):
        print(f"--- {item['name']} ---")
        print(f"Summary: {summary}")
        print()

    success_count = sum(1 for r in results if r)
    print(f"=== Test complete: {success_count}/{len(items)} entities enriched ===")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
